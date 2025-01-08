import express from 'express'
import cors from 'cors'
import WebTorrent from 'webtorrent'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

// Optional: If you need a custom store, install and import fs-chunk-store:
import FSChunkStore from 'fs-chunk-store'

// __dirname and __filename equivalents in ESM
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// Create an Express app
const app = express()
app.use(cors())            // Allow cross-origin requests (e.g., from React)
app.use(express.json())    // Parse JSON request bodies

// Create a global WebTorrent client
const client = new WebTorrent()

// We'll keep track of torrents in a map: { infoHash: { torrent, sseClients: Set(res) } }
const torrents = {}

// POST /api/torrents => Add torrent using magnet URI
app.post('/api/torrents', (req, res) => {
  const { magnetUri } = req.body
  if (!magnetUri) {
    return res.status(400).json({ error: 'magnetUri is required' })
  }

  // Add the torrent to the client
  // By default, WebTorrent on Node uses fs-chunk-store. 
  // We'll tell it to download files into /mnt/efs/fs1. 
  // This means each file will appear under /mnt/efs/fs1/<torrent name> or <infoHash>/<file>.
  client.add(
    magnetUri,
    {
      path: '/mnt/efs/fs1' // Make sure this directory exists & is writable
      // If you want a custom chunk store or a subfolder, you could do:
      // store: (chunkLength) => new FSChunkStore(chunkLength, { path: '/mnt/efs/fs1/my-folder' })
    },
    (torrent) => {
      console.log(`Torrent added. Info Hash: ${torrent.infoHash}`)

      // Store reference
      torrents[torrent.infoHash] = {
        torrent,
        sseClients: new Set() // We'll broadcast progress to these SSE clients
      }

      // Listen for download events
      torrent.on('download', () => {
        broadcastProgress(torrent.infoHash)
      })
      // Listen for upload events (if you're seeding)
      torrent.on('upload', () => {
        broadcastProgress(torrent.infoHash)
      })
      // Completed
      torrent.on('done', () => {
        console.log(`Torrent ${torrent.infoHash} downloaded completely!`)
        broadcastProgress(torrent.infoHash)
      })

      // Respond with the infoHash so the client can open an SSE connection
      res.json({ infoHash: torrent.infoHash })
    }
  )
})

// GET /api/torrents/:infoHash/events => Server-Sent Events for progress
app.get('/api/torrents/:infoHash/events', (req, res) => {
  const { infoHash } = req.params
  const record = torrents[infoHash]
  if (!record) {
    return res.status(404).send('Torrent not found')
  }

  // Setup SSE headers
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive'
  })

  // Add this response object to the SSE clients for this torrent
  record.sseClients.add(res)

  // Remove it if the client closes the connection
  req.on('close', () => {
    record.sseClients.delete(res)
  })
})

// Helper function to broadcast progress to all connected SSE clients
function broadcastProgress(infoHash) {
  const record = torrents[infoHash]
  if (!record) return

  const { torrent, sseClients } = record
  // Gather some stats
  const progressData = {
    infoHash: torrent.infoHash,
    progress: torrent.progress,          // 0..1
    downloadSpeed: torrent.downloadSpeed, // bytes/sec
    uploadSpeed: torrent.uploadSpeed,     // bytes/sec
    numPeers: torrent.numPeers,
    downloaded: torrent.downloaded,       // bytes
    uploaded: torrent.uploaded,           // bytes
    ratio: torrent.ratio                  // uploaded / downloaded
  }

  // Send an SSE event named 'progress' with JSON data
  for (const clientRes of sseClients) {
    clientRes.write(`event: progress\n`)
    clientRes.write(`data: ${JSON.stringify(progressData)}\n\n`)
  }
}

// Start the server on port 4000 (or any you choose)
const PORT = process.env.PORT || 4000
app.listen(PORT, () => {
  console.log(`Server is running on port ${PORT}`)
})

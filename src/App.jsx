import React, { useState, useEffect } from 'react'

function App() {
  const [magnetUri, setMagnetUri] = useState('')
  const [infoHash, setInfoHash] = useState(null)
  const [progress, setProgress] = useState(0)
  const [downloadSpeed, setDownloadSpeed] = useState(0)
  const [uploadSpeed, setUploadSpeed] = useState(0)
  const [numPeers, setNumPeers] = useState(0)
  const [ratio, setRatio] = useState(0)
  const [status, setStatus] = useState('Idle')

  // This function sends the magnet URI to our Node server
  const handleStartDownload = async () => {
    if (!magnetUri) return

    try {
      setStatus('Starting download...')
      // POST request to the server
      const res = await fetch('/api/torrents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ magnetUri })
      })
      const data = await res.json()

      if (data.infoHash) {
        // Save the infoHash so we can open an SSE connection
        setInfoHash(data.infoHash)
        setStatus('Downloading...')
      } else {
        setStatus('Error: Server did not return infoHash')
      }
    } catch (err) {
      console.error('Error starting download:', err)
      setStatus('Error starting download')
    }
  }

  // Whenever we get a new infoHash, open an SSE connection for progress updates
  useEffect(() => {
    if (!infoHash) return

    // SSE endpoint
    const eventsUrl = `/api/torrents/${infoHash}/events`
    const eventSource = new EventSource(eventsUrl)

    // Listen for 'progress' events from the server
    eventSource.addEventListener('progress', (event) => {
      const data = JSON.parse(event.data)
      setProgress(data.progress)                  // 0..1
      setDownloadSpeed(data.downloadSpeed)        // bytes/sec
      setUploadSpeed(data.uploadSpeed)            // bytes/sec
      setNumPeers(data.numPeers)
      setRatio(data.ratio)

      if (data.progress >= 1) {
        setStatus('Seeding')
      }
    })

    // Handle errors (e.g., network issues, server down)
    eventSource.onerror = (err) => {
      console.error('SSE error', err)
      setStatus('Error receiving progress updates')
    }

    // Cleanup: close the SSE connection if this component unmounts or infoHash changes
    return () => {
      eventSource.close()
    }
  }, [infoHash])

  // Helper to format bytes for display
  const formatBytes = (bytes, decimals = 2) => {
    if (!+bytes) return '0 Bytes'
    const k = 1024
    const dm = decimals < 0 ? 0 : decimals
    const sizes = ['Bytes','KB','MB','GB','TB','PB','EB','ZB','YB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`
  }

  // Render a simple UI
  return (
    <div style={{ padding: '1rem' }}>
      <h1>WebTorrent + EFS Demo</h1>

      <div style={{ marginBottom: '1rem' }}>
        <input
          type="text"
          placeholder="Magnet URI"
          value={magnetUri}
          onChange={(e) => setMagnetUri(e.target.value)}
          style={{ width: '300px', marginRight: '0.5rem' }}
        />
        <button onClick={handleStartDownload}>Start Download</button>
      </div>

      <p>Status: {status}</p>
      <p>Progress: {(progress * 100).toFixed(2)}%</p>
      <p>Download Speed: {formatBytes(downloadSpeed)}/s</p>
      <p>Upload Speed: {formatBytes(uploadSpeed)}/s</p>
      <p>Peers: {numPeers}</p>
      <p>Ratio: {ratio.toFixed(2)}</p>
    </div>
  )
}

export default App

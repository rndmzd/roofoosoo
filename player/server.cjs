// server.js
const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const path = require("path");

const app = express();
const server = http.createServer(app);
const io = new Server(server);

// Store current playback in memory
// In production, you might store this in a DB or keep a timer
let currentPlayback = {
  status: "PAUSED", // or "PLAYING"
  time: 0           // Current position in seconds
};

// Serve static files (index.html, etc.) from "public" folder
app.use(express.static(path.join(__dirname, "public")));

app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

io.on("connection", (socket) => {
  console.log("A user connected:", socket.id);

  // 1) Send current playback state to the NEW user
  socket.emit("currentPlayback", currentPlayback);

  // 2) When the owner updates playback
  socket.on("playbackCommand", (data) => {
    // data might be: { action: "PLAY" | "PAUSE", time: <number> }
    currentPlayback.time = data.time;
    if (data.action === "PLAY") {
      currentPlayback.status = "PLAYING";
    } else if (data.action === "PAUSE") {
      currentPlayback.status = "PAUSED";
    }

    // Broadcast to all other clients
    socket.broadcast.emit("playbackCommand", data);
  });

  // 3) (Optional) owner sends frequent "timeUpdate" events
  socket.on("timeUpdate", (newTime) => {
    currentPlayback.time = newTime;
  });

  socket.on("disconnect", () => {
    console.log("User disconnected:", socket.id);
  });
});

const PORT = 3000;
server.listen(PORT, () => {
  console.log("Server listening on http://localhost:" + PORT);
});

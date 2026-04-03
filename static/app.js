let pc;
let localStream;
let isConnected = false;

const connectBtn = document.getElementById("connect-btn");
const statusText = document.getElementById("status-text");
const activityRing = document.getElementById("activity-ring");
const remoteAudio = document.getElementById("remote-audio");

connectBtn.addEventListener("click", toggleConnection);

async function toggleConnection() {
    if (isConnected) {
        disconnect();
    } else {
        await connect();
    }
}

async function connect() {
    try {
        statusText.innerText = "Requesting microphone access...";
        localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        statusText.innerText = "Connecting to Maya...";
        pc = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });

        // Add local stream tracks to PC
        localStream.getTracks().forEach(track => {
            pc.addTrack(track, localStream);
        });

        // When remote track comes in, play it
        pc.ontrack = (event) => {
            if (event.streams && event.streams[0]) {
                remoteAudio.srcObject = event.streams[0];
                console.log("Remote audio stream mapped");
            }
        };

        // ICE Connection State handling
        pc.oniceconnectionstatechange = () => {
            if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") {
                statusText.innerText = "Connected. Speak now!";
                connectBtn.innerHTML = '<span class="icon">🛑</span> End Session';
                connectBtn.classList.add("connected");
                activityRing.classList.add("active");
                isConnected = true;
            } else if (pc.iceConnectionState === "disconnected" || pc.iceConnectionState === "failed") {
                disconnect();
            }
        };

        // Create initial WebRTC Offer
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // Wait a tiny bit for ICE gathering (very simple approach for localhost)
        await new Promise((resolve) => {
            if (pc.iceGatheringState === "complete") {
                resolve();
            } else {
                const checkState = () => {
                    if (pc.iceGatheringState === "complete") {
                        pc.removeEventListener("icegatheringstatechange", checkState);
                        resolve();
                    }
                };
                pc.addEventListener("icegatheringstatechange", checkState);
                
                // fallback timeout
                setTimeout(resolve, 1000);
            }
        });

        // Send SDP Offer to FastAPI web server
        const response = await fetch("/offer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type
            })
        });

        const answer = await response.json();
        
        // Ensure remote descriptor is an answer
        await pc.setRemoteDescription(new RTCSessionDescription(answer));
        
    } catch (e) {
        console.error("Connection failed:", e);
        statusText.innerText = `Error: ${e.message}`;
        disconnect();
    }
}

function disconnect() {
    if (pc) {
        pc.close();
        pc = null;
    }
    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        localStream = null;
    }
    isConnected = false;
    statusText.innerText = "Session ended";
    connectBtn.innerHTML = '<span class="icon">🎤</span> Tap to Speak';
    connectBtn.classList.remove("connected");
    activityRing.classList.remove("active");
    if (remoteAudio.srcObject) {
         remoteAudio.srcObject = null;
    }
}

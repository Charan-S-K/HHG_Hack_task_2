document.addEventListener("DOMContentLoaded", () => {
    const micBtn = document.getElementById("mic-btn");
    const statusText = document.getElementById("status-text");
    const resultsSection = document.getElementById("results-section");
    const queryDisplay = document.getElementById("query-display");
    const answerCard = document.getElementById("answer-card");
    const answerDisplay = document.getElementById("answer-display");
    const chunkCount = document.getElementById("chunk-count");
    const contextCard = document.getElementById("context-card");
    const chunksList = document.getElementById("chunks-list");

    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    // Add click handler to mic button
    micBtn.addEventListener("click", () => {
        if (!isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    });

    // Fallback: double click mic button to enter text query manually (useful for non-audio testing)
    micBtn.addEventListener("dblclick", () => {
        const textQuery = prompt("ध्वनि के स्थान पर पाठ प्रश्न दर्ज करें (Enter text query):");
        if (textQuery && textQuery.trim()) {
            submitTextQuery(textQuery.trim(), null);
        }
    });

    async function startRecording() {
        audioChunks = [];
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Check for supported formats
            let options = { mimeType: 'audio/webm' };
            if (!MediaRecorder.isTypeSupported(options.mimeType)) {
                options = { mimeType: 'audio/ogg' };
                if (!MediaRecorder.isTypeSupported(options.mimeType)) {
                    options = { mimeType: '' }; // Fallback to default
                }
            }

            mediaRecorder = new MediaRecorder(stream, options);
            
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/wav' });
                // Stop all tracks to release microphone
                stream.getTracks().forEach(track => track.stop());
                
                await uploadAudio(audioBlob);
            };

            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add("recording");
            statusText.innerText = "सुन रहा हूँ... टैप करें रोकें (Listening... Tap to stop)";
            statusText.classList.add("text-highlight");
            
            // Reset results view
            resultsSection.classList.add("hidden");
            answerCard.classList.add("hidden");
            contextCard.classList.add("hidden");
        } catch (err) {
            console.error("Microphone access failed:", err);
            alert("माइक्रोफ़ोन एक्सेस विफल रहा। पाठ प्रश्न दर्ज करने के लिए माइक बटन पर डबल-क्लिक करें।\n" +
                  "(Microphone access failed. Double-click the mic button to type your query instead.)");
            statusText.innerText = "Double-click to type";
        }
    }

    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            micBtn.classList.remove("recording");
            statusText.innerText = "ट्रांसक्राइब कर रहा हूँ... (Transcribing...)";
            statusText.classList.remove("text-highlight");
        }
    }

    async function uploadAudio(audioBlob) {
        const formData = new FormData();
        // Sarvam accepts wav, mp3, ogg etc.
        const fileExt = mediaRecorder.mimeType.includes("webm") ? "webm" : "wav";
        formData.append("file", audioBlob, `audio.${fileExt}`);

        try {
            const response = await fetch("/api/stt", {
                method: "POST",
                body: formData
            });

            if (!response.ok) {
                let errorMsg = `STT failed (Status ${response.status})`;
                try {
                    const errData = await response.json();
                    if (errData && errData.detail) {
                        errorMsg = errData.detail;
                    }
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const data = await response.json();
            const transcript = data.transcript;
            const languageCode = data.language_code || null;

            if (!transcript || transcript.trim() === "") {
                statusText.innerText = "कोई आवाज़ नहीं सुनी गई (No voice detected)";
                return;
            }

            submitTextQuery(transcript, languageCode);
        } catch (err) {
            console.error("STT transcription failed:", err);
            statusText.innerText = "STT विफल (STT Failed)";
            alert(`STT विफल रहा: ${err.message}`);
        }
    }

    async function submitTextQuery(queryText, languageCode = null) {
        // Show status
        statusText.innerText = "उत्तर खोज रहा हूँ... (Retrieving & Generating...)";
        
        // Show results section
        resultsSection.classList.remove("hidden");
        queryDisplay.innerText = queryText;
        
        // Show answer placeholder
        answerCard.classList.remove("hidden");
        answerDisplay.innerText = "खोज एवं उत्तर उत्पादन चल रहा है (Generating answer)...";
        chunkCount.innerText = "0";
        contextCard.classList.add("hidden");

        try {
            const response = await fetch("/api/query", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ query: queryText, language_code: languageCode })
            });

            if (!response.ok) {
                let errorMsg = `RAG query failed (Status ${response.status})`;
                try {
                    const errData = await response.json();
                    if (errData && errData.detail) {
                        errorMsg = errData.detail;
                    }
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const data = await response.json();
            
            // Display answer
            answerDisplay.innerText = data.answer;
            chunkCount.innerText = data.retrieved_chunk_count;

            // Display retrieved chunks
            chunksList.innerHTML = "";
            if (data.context && data.context.length > 0) {
                contextCard.classList.remove("hidden");
                data.context.forEach((chunk, index) => {
                    const chunkEl = document.createElement("div");
                    chunkEl.className = "chunk-item";
                    
                    const relevanceType = chunk.is_selected ? "प्रासंगिक (Relevant)" : "अतिरिक्त (Context)";
                    
                    chunkEl.innerHTML = `
                        <div class="chunk-header">
                            <span>टुकड़ा ${index + 1} | Query ID: ${chunk.query_id}</span>
                            <span>दूरी (L2): ${chunk.distance.toFixed(4)} | ${relevanceType}</span>
                        </div>
                        <p class="mono-body">${chunk.text}</p>
                    `;
                    chunksList.appendChild(chunkEl);
                });
            } else {
                contextCard.classList.add("hidden");
            }
            
            statusText.innerText = "सफल! (Completed!)";
        } catch (err) {
            console.error("RAG pipeline failed:", err);
            answerDisplay.innerText = `त्रुटि: ${err.message}`;
            alert(`RAG पाइपलाइन विफल रही: ${err.message}`);
            statusText.innerText = "त्रुटि (Error)";
        }
    }
});

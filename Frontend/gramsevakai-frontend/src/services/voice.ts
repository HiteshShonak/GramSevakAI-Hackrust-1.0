import { Audio } from "expo-av";
import { apiFetch } from "@/services/api";

// Global recording state
let recording: Audio.Recording | null = null;

/** Request mic permission + start recording */
export async function startRecording(): Promise<void> {
  try {
    // Configure audio session
    await Audio.setAudioModeAsync({
      allowsRecordingIOS: true,
      playsInSilentModeIOS: true,
    });

    // Create and start recording
    const rec = new Audio.Recording();
    await rec.prepareToRecordAsync(
      Audio.RecordingOptionsPresets.HIGH_QUALITY
    );
    await rec.startAsync();
    recording = rec;
  } catch (err) {
    console.error("Failed to start recording:", err);
    throw err;
  }
}

/**
 * Stop recording and return the file URI.
 * Returns null if no recording was in progress.
 */
export async function stopRecording(): Promise<string | null> {
  if (!recording) return null;
  try {
    await recording.stopAndUnloadAsync();
    const uri = recording.getURI() || null;
    return uri;
  } catch (err) {
    console.error("Failed to stop recording:", err);
    return null;
  } finally {
    recording = null;
  }
}

/** Cancel recording without sending */
export async function cancelRecording(): Promise<void> {
  if (!recording) return;
  try {
    await recording.stopAndUnloadAsync();
  } catch {
    /* ignore */
  }
  recording = null;
}

export function isRecording(): boolean {
  return recording !== null;
}

/** Send recorded audio to backend for transcription + chat processing */
export async function sendVoiceMessage(
  fileUri: string,
  language: string,
  token: string
): Promise<{ messages: string[]; language?: string }> {
  // Read file as base64
  const response = await fetch(fileUri);
  const blob = await response.blob();
  const base64 = await blobToBase64(blob);

  return apiFetch<{ messages: string[]; language?: string }>("/api/v1/chat/voice", {
    method: "POST",
    token,
    body: JSON.stringify({
      audio_base64: base64,
      language,
    }),
  });
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      // Strip data:audio/...;base64, prefix if present
      const base64 = result.includes(",") ? result.split(",")[1] : result;
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Records microphone audio and encodes it to a 16-bit PCM WAV Blob in the
// browser. We use WAV (rather than the MediaRecorder default of webm/opus)
// because the Gemini API accepts WAV directly, so no server-side transcoding
// is needed. Transcription itself is done by Gemini on the backend.

function encodeWav(chunks: Float32Array[], sampleRate: number): Blob {
  let total = 0;
  for (const c of chunks) total += c.length;
  const samples = new Float32Array(total);
  let offset = 0;
  for (const c of chunks) {
    samples.set(c, offset);
    offset += c.length;
  }

  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (pos: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(pos + i, str.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // audio format = PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let pos = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(pos, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    pos += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

export function micSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof (window.AudioContext || (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext) !==
      "undefined"
  );
}

export class WavRecorder {
  private stream?: MediaStream;
  private ctx?: AudioContext;
  private processor?: ScriptProcessorNode;
  private source?: MediaStreamAudioSourceNode;
  private chunks: Float32Array[] = [];
  private rate = 44100;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    this.rate = this.ctx.sampleRate;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.processor.onaudioprocess = (e: AudioProcessingEvent) => {
      this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    };
    this.source.connect(this.processor);
    // ScriptProcessor only fires while connected to the graph; its output is
    // never written, so nothing is played back (no echo).
    this.processor.connect(this.ctx.destination);
  }

  /** Stop recording and return the recorded audio as a WAV blob (null if silent). */
  async stop(): Promise<Blob | null> {
    const chunks = this.chunks;
    const rate = this.rate;
    this.teardown();
    const total = chunks.reduce((n, c) => n + c.length, 0);
    if (total === 0) return null;
    return encodeWav(chunks, rate);
  }

  /** Abort without producing a blob (chat switch / unmount). */
  cancel(): void {
    this.teardown();
  }

  private teardown(): void {
    try {
      this.processor?.disconnect();
      this.source?.disconnect();
    } catch {
      /* ignore */
    }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.chunks = [];
    this.stream = undefined;
    this.ctx = undefined;
    this.processor = undefined;
    this.source = undefined;
  }
}

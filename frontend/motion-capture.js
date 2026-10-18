(function(root) {
  'use strict';
  class MotionCapture {
    constructor(video, deps = {}) {
      this.video = video; this.deps = deps; this.pending = new Map();
      this.generation = 0; this.sequence = 0; this.ready = false;
    }
    ask(type, fields = {}, transfer = [], timeout = 1000) {
      return new Promise((resolve, reject) => {
        const id = ++this.sequence;
        const timer = setTimeout(() => {
          this.pending.delete(id); reject(new Error('Local pose processing timed out'));
        }, timeout);
        this.pending.set(id, (data) => {
          clearTimeout(timer); data.error ? reject(new Error('Local pose processing failed')) : resolve(data);
        });
        this.worker.postMessage({id, type, ...fields}, transfer);
      });
    }
    async warm() {
      if (this.ready) return;
      const WorkerClass = this.deps.Worker || Worker;
      this.worker = new WorkerClass('/assets/motion-worker.js', {type: 'module'});
      this.worker.onmessage = ({data}) => {
        const done = this.pending.get(data.id);
        this.pending.delete(data.id); if (done) done(data);
      };
      await this.ask('init', {}, [], 30000); this.ready = true;
    }
    stopTracks() {
      if (this.stream) for (const track of this.stream.getTracks()) track.stop();
      this.stream = null; this.video.srcObject = null;
    }
    cancel() {
      this.generation++; clearTimeout(this.limit); this.stopTracks();
      if (this.abort) this.abort();
      if (this.worker) this.worker.terminate();
      this.ready = false;
      for (const done of this.pending.values()) done({error: true});
      this.pending.clear();
    }
    async capture() {
      if (!this.ready) throw new Error('Prepare the local pose model first');
      if (this.capturing) throw new Error('A movement capture is already running');
      this.capturing = true;
      const generation = ++this.generation;
      const media = this.deps.mediaDevices || navigator.mediaDevices;
      const now = this.deps.now || (() => performance.now());
      const bitmap = this.deps.bitmap || ((video) => createImageBitmap(video));
      const nextFrame = this.deps.nextFrame || (() => new Promise(requestAnimationFrame));
      const frames = [];
      const aborted = new Promise((resolve) => { this.abort = () => resolve(null); });
      const race = (task) => Promise.race([task, aborted]);
      try {
        const stream = await media.getUserMedia({audio: false,
          video: {facingMode: 'user', width: {ideal: 640}, height: {ideal: 480}}});
        if (generation !== this.generation) {
          for (const track of stream.getTracks()) track.stop(); return null;
        }
        this.stream = stream; this.video.srcObject = stream;
        const started = now();
        let lastVideoTime = -1, lastDispatch = -Infinity, expired = false;
        const timer = this.deps.setTimeout || setTimeout;
        this.limit = timer(() => {
          expired = true; this.stopTracks(); this.abort();
        }, 10000);
        if (!await race(this.video.play().then(() => true))) return null;
        while (!expired && now() - started < 10000 && generation === this.generation) {
          if (this.video.currentTime !== lastVideoTime && this.video.readyState >= 2
              && now() - lastDispatch >= 1000 / 30) {
            lastVideoTime = this.video.currentTime; lastDispatch = now();
            const t = (now() - started) / 1000;
            const frame = await race(Promise.resolve(bitmap(this.video)).then((image) => {
              if (generation !== this.generation || expired) { image.close(); return null; }
              return image;
            }));
            if (!frame) break;
            if (generation !== this.generation || expired) { frame.close(); break; }
            const data = await race(this.ask('frame', {bitmap: frame, timestamp: now()}, [frame]));
            if (!data) break;
            frames.push({t, landmarks: data.landmarks});
          }
          await race(nextFrame());
        }
        if (generation !== this.generation) return null;
        const core = this.deps.core || root.MotionCore;
        return core.measure(frames, Math.min(10, (now() - started) / 1000));
      } finally { this.capturing = false; this.abort = null; clearTimeout(this.limit); this.stopTracks(); }
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {MotionCapture};
  else root.MotionCapture = MotionCapture;
})(typeof window !== 'undefined' ? window : globalThis);

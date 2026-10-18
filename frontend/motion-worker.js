// Every executable/model URL is self-hosted and pinned in vendor/mediapipe/manifest.json.
import {FilesetResolver, PoseLandmarker} from './vendor/mediapipe/vision_bundle.mjs';
let model;
self.onmessage = async ({data}) => {
  const {id, type} = data;
  try {
    if (type === 'init') {
      const files = await FilesetResolver.forVisionTasks('/assets/vendor/mediapipe/wasm', true);
      model = await PoseLandmarker.createFromOptions(files, {
        baseOptions: {modelAssetPath: '/assets/vendor/mediapipe/pose_landmarker_lite.task',
          delegate: 'CPU'}, runningMode: 'VIDEO', numPoses: 1,
        minPoseDetectionConfidence: .5, minPosePresenceConfidence: .5,
        minTrackingConfidence: .5, outputSegmentationMasks: false});
      self.postMessage({id, ready: true});
    } else if (type === 'frame') {
      try {
        if (!model) throw new Error('not ready');
        const result = model.detectForVideo(data.bitmap, data.timestamp);
        self.postMessage({id, landmarks: result.landmarks.length === 1 ? result.landmarks[0] : null});
      } finally { data.bitmap.close(); }
    }
  } catch (_) {
    // Never log image/model request details or serialize frames into errors.
    self.postMessage({id, error: true});
  }
};

// Re-encode a screen recording as a small, web-friendly H.264 MP4 (no audio,
// fast start), using only macOS AVFoundation — no ffmpeg needed.
//
// Usage (from the repo root):
//   swift tools/encode-video.swift in.mov out.mp4 [maxWidth=1920] [kbps=3000]
//
// Also writes out.jpg, the first frame, for the <video> poster.
import AVFoundation
import AppKit

let args = CommandLine.arguments
guard args.count >= 3 else {
    print("usage: swift tools/encode-video.swift in.mov out.mp4 [maxWidth] [kbps]"); exit(1)
}
let src = URL(fileURLWithPath: args[1]), dst = URL(fileURLWithPath: args[2])
let maxWidth = args.count > 3 ? Double(args[3])! : 1920
let kbps = args.count > 4 ? Int(args[4])! : 3000

let asset = AVURLAsset(url: src)
guard let track = asset.tracks(withMediaType: .video).first else { print("no video track"); exit(1) }
let size = track.naturalSize.applying(track.preferredTransform)
let srcW = abs(size.width), srcH = abs(size.height)
let scale = min(1, maxWidth / srcW)
// H.264 wants even dimensions
let outW = Int((srcW * scale / 2).rounded()) * 2, outH = Int((srcH * scale / 2).rounded()) * 2
let fps = track.nominalFrameRate > 0 ? track.nominalFrameRate : 30

try? FileManager.default.removeItem(at: dst)
let reader = try AVAssetReader(asset: asset)
let out = AVAssetReaderTrackOutput(track: track, outputSettings: [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
])
reader.add(out)

let writer = try AVAssetWriter(outputURL: dst, fileType: .mp4)
writer.shouldOptimizeForNetworkUse = true          // moov atom first: starts playing sooner
let input = AVAssetWriterInput(mediaType: .video, outputSettings: [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: outW,
    AVVideoHeightKey: outH,
    AVVideoScalingModeKey: AVVideoScalingModeResizeAspect,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: kbps * 1000,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        AVVideoMaxKeyFrameIntervalKey: Int(fps * 2),
        AVVideoAllowFrameReorderingKey: true,
    ],
])
input.transform = track.preferredTransform
input.expectsMediaDataInRealTime = false
writer.add(input)

reader.startReading()
writer.startWriting()
writer.startSession(atSourceTime: .zero)

let done = DispatchSemaphore(value: 0)
input.requestMediaDataWhenReady(on: DispatchQueue(label: "encode")) {
    while input.isReadyForMoreMediaData {
        if let buf = out.copyNextSampleBuffer() {
            input.append(buf)
        } else {
            input.markAsFinished()
            writer.finishWriting { done.signal() }
            return
        }
    }
}
done.wait()
guard writer.status == .completed else { print("failed:", writer.error ?? "unknown"); exit(1) }

// poster: first frame as JPEG
let gen = AVAssetImageGenerator(asset: AVURLAsset(url: dst))
gen.appliesPreferredTrackTransform = true
gen.requestedTimeToleranceBefore = .zero
gen.requestedTimeToleranceAfter = .zero
if let cg = try? gen.copyCGImage(at: .zero, actualTime: nil) {
    let rep = NSBitmapImageRep(cgImage: cg)
    let jpg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.8])!
    try jpg.write(to: dst.deletingPathExtension().appendingPathExtension("jpg"))
}
let bytes = (try FileManager.default.attributesOfItem(atPath: dst.path)[.size] as! Int)
print("\(outW)x\(outH) @ \(fps)fps, \(kbps) kbps -> \(bytes / 1024) KB")

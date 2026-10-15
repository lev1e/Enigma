// Apple Vision OCR: prints one JSON array of words {t,x0,y0,x1,y1,line} in image pixels (origin top-left).
import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count > 1 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL
guard let src = CGImageSourceCreateWithURL(url, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { exit(3) }
let W = Double(img.width), H = Double(img.height)
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
req.recognitionLanguages = ["ru-RU", "en-US"]
req.minimumTextHeight = 0
do { try VNImageRequestHandler(cgImage: img, options: [:]).perform([req]) } catch { exit(4) }
var out: [[String: Any]] = []
var line = 0
for obs in (req.results ?? []) {
    guard let cand = obs.topCandidates(1).first else { continue }
    let s = cand.string
    var idx = s.startIndex
    while idx < s.endIndex {
        while idx < s.endIndex && s[idx].isWhitespace { idx = s.index(after: idx) }
        if idx >= s.endIndex { break }
        var end = idx
        while end < s.endIndex && !s[end].isWhitespace { end = s.index(after: end) }
        let r = idx..<end
        if let box = try? cand.boundingBox(for: r) {
            let b = box.boundingBox
            // Направление текста по основанию слова: Vision читает и повёрнутый текст, рамка у него вертикальная.
            let ang = atan2((box.bottomRight.y - box.bottomLeft.y) * H, (box.bottomRight.x - box.bottomLeft.x) * W) * 180 / Double.pi
            let rot = ((Int((ang / 90).rounded()) * 90) % 360 + 360) % 360
            var cx: [[Double]] = []
            var cbox: [[Double]] = []
            var ci = idx
            while ci < end {
                let nx = s.index(after: ci)
                if let cb = try? cand.boundingBox(for: ci..<nx) {
                    let q = cb.boundingBox
                    cx.append([q.minX * W, q.maxX * W])
                    cbox.append([q.minX * W, (1 - q.maxY) * H, q.maxX * W, (1 - q.minY) * H])
                }
                ci = nx
            }
            var item: [String: Any] = ["t": String(s[r]), "x0": b.minX * W, "x1": b.maxX * W,
                        "y0": (1 - b.maxY) * H, "y1": (1 - b.minY) * H, "line": line, "cx": cx, "conf": Double(cand.confidence)]
            if rot != 0 { item["rot"] = rot; item["cb"] = cbox }
            out.append(item)
        }
        idx = end
    }
    line += 1
}
let data = try JSONSerialization.data(withJSONObject: out)
FileHandle.standardOutput.write(data)

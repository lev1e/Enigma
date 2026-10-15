// Apple Vision barcode/QR detector: prints one JSON array of {p,s,x0,y0,x1,y1} in image pixels (origin top-left).
// p = decoded payload ("" when the code is found but cannot be decoded), s = symbology.
// Optional second argument: rotation 0/90/180/270 is not needed here; Vision finds codes in any orientation.
import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count > 1 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL
guard let src = CGImageSourceCreateWithURL(url, nil), let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { exit(3) }
let W = Double(img.width), H = Double(img.height)
let req = VNDetectBarcodesRequest()
do { try VNImageRequestHandler(cgImage: img, options: [:]).perform([req]) } catch { exit(4) }
var out: [[String: Any]] = []
for obs in (req.results ?? []) {
    let b = obs.boundingBox
    out.append(["p": obs.payloadStringValue ?? "", "s": obs.symbology.rawValue,
                "x0": b.minX * W, "x1": b.maxX * W, "y0": (1 - b.maxY) * H, "y1": (1 - b.minY) * H])
}
let data = try JSONSerialization.data(withJSONObject: out)
FileHandle.standardOutput.write(data)

// qr_maker <payload> <out.png> [code128]: writes a QR (or Code128) image for tests.
import Foundation
import CoreImage
import AppKit

let payload = CommandLine.arguments[1]
let out = CommandLine.arguments[2]
let kind = CommandLine.arguments.count > 3 ? CommandLine.arguments[3] : "qr"
let filter = CIFilter(name: kind == "code128" ? "CICode128BarcodeGenerator" : "CIQRCodeGenerator")!
filter.setValue(payload.data(using: .utf8)!, forKey: "inputMessage")
let scale: CGFloat = kind == "code128" ? 4 : 8
let image = filter.outputImage!.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
let rep = NSBitmapImageRep(ciImage: image)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))

// Experimental stub — not used by bw/tts.py (macOS `say` only). Intentionally incomplete.
import AVFoundation
import Foundation

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("usage: bw_speak_av <voice-preference> <output.m4a> < text\n", stderr)
    exit(2)
}
let pref = args[1].lowercased()
let outPath = args[2]
let text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
guard !text.isEmpty else { exit(3) }

func pickVoice() -> AVSpeechSynthesisVoice? {
    let voices = AVSpeechSynthesisVoice.speechVoices()
    let siriIds = [
        "com.apple.speech.synthesis.voice.custom.siri.simone.premium",
        "com.apple.speech.synthesis.voice.custom.siri.nora.premium",
        "com.apple.speech.synthesis.voice.custom.siri.aaron.premium",
        "com.apple.speech.synthesis.voice.custom.siri.quinn.premium",
        "com.apple.speech.synthesis.voice.custom.siri.damon.premium",
    ]
    if pref.contains("siri") && pref.contains("2") {
        for id in siriIds {
            if let v = AVSpeechSynthesisVoice(identifier: id) { return v }
        }
    }
    for v in voices where v.quality == .premium && v.language.hasPrefix("en") {
        if pref.contains("siri") { return v }
    }
    if let v = AVSpeechSynthesisVoice(language: "en-US") { return v }
    return AVSpeechSynthesisVoice(language: "en-US")
}

guard let voice = pickVoice() else {
    fputs("error: no voice\n", stderr)
    exit(1)
}
fputs("voice: \(voice.identifier) \(voice.name)\n", stderr)

let utterance = AVSpeechUtterance(string: text)
utterance.voice = voice
utterance.rate = AVSpeechUtteranceDefaultSpeechRate

let out = URL(fileURLWithPath: outPath)
let synth = AVSpeechSynthesizer()
let sem = DispatchSemaphore(value: 0)
var ok = false
class Del: NSObject, AVSpeechSynthesizerDelegate {
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        ok = true
        sem.signal()
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        sem.signal()
    }
}
let del = Del()
synth.delegate = del
if #available(macOS 14.0, *) {
    var err: NSError?
    synth.write(utterance) { buffer in
        guard let buffer = buffer else {
            sem.signal()
            return
        }
        // append buffers - simplified: use speak to file via write API
    }
}
fputs("bw_speak_av: not implemented — use macOS say(1) via bw/tts.py\n", stderr)
exit(1)
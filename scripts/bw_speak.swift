import AppKit
import Foundation

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("usage: bw_speak <voice-name> <output.aiff> < textfile\n", stderr)
    exit(2)
}
let voiceName = args[1]
let outPath = args[2]
let text = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) ?? ""
guard !text.isEmpty else { exit(3) }

let out = URL(fileURLWithPath: outPath)
let synth = NSSpeechSynthesizer()

func matchVoice(_ query: String) -> NSSpeechSynthesizer.VoiceName? {
    let q = query.lowercased()
    var fallback: NSSpeechSynthesizer.VoiceName?
    for v in NSSpeechSynthesizer.availableVoices {
        let attrs = NSSpeechSynthesizer.attributes(forVoice: v)
        let name = ((attrs[.name] as? String) ?? "").lowercased()
        let id = v.rawValue.lowercased()
        if name == q || id == q { return v }
        if name.contains("voice 2") && (q.contains("siri") && q.contains("2")) { return v }
        if name.contains(q) || q.contains(name) { fallback = v }
        if id.contains("siri") && q.contains("siri") { fallback = v }
    }
    return fallback
}

let wantsSiri2 = voiceName.lowercased().contains("siri") && voiceName.contains("2")
if let v = matchVoice(voiceName) {
    synth.setVoice(v)
} else if let prefs = NSDictionary(contentsOf: URL(fileURLWithPath: NSHomeDirectory() + "/Library/Preferences/com.apple.speech.voice.prefs.plist")),
          let selected = prefs["SelectedVoiceName"] as? String,
          let v = matchVoice(selected) {
    synth.setVoice(v)
    fputs("note: using Spoken Content voice \(selected)\n", stderr)
} else if wantsSiri2,
          let prefs = NSDictionary(contentsOf: URL(fileURLWithPath: NSHomeDirectory() + "/Library/Preferences/com.apple.speech.voice.prefs.plist")),
          let selected = prefs["SelectedVoiceName"] as? String {
    fputs("use_say:\(selected)\n", stderr)
    exit(4)
} else {
    fputs("error: voice not found: \(voiceName)\n", stderr)
    exit(1)
}

synth.startSpeaking(text, to: out)
while synth.isSpeaking {
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
}
exit(0)
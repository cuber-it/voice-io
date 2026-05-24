"""CLI — voice-input command line interface."""
import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description="voice-input — wakeword + Whisper")
    parser.add_argument("--wakeword",  default="hey_jarvis",  help="wake-word (default: hey_jarvis)")
    parser.add_argument("--model",     default="base",         help="Whisper model (default: base)")
    parser.add_argument("--language",  default="de",           help="language (default: de)")
    parser.add_argument("--device",    default=None,           help="microphone device name")
    parser.add_argument("--list-devices", action="store_true", help="list microphone devices")
    parser.add_argument("--once",      action="store_true",    help="capture one utterance and exit")
    parser.add_argument("--verbose",   action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    from voice_input import VoiceInput, list_input_devices

    if args.list_devices:
        for d in list_input_devices():
            print(f"  [{d['index']}] {d['name']} ({d['channels']}ch)")
        return

    voice = VoiceInput(
        wakeword=args.wakeword,
        whisper_model=args.model,
        language=args.language,
        device=args.device,
    )

    if args.once:
        text = voice.listen_once()
        print(text or "(nothing heard)")
        return

    print(f"Listening for '{args.wakeword}'… (Ctrl+C to stop)")

    def handle(text: str) -> None:
        print(f"> {text}")

    voice.start(on_text=handle)
    try:
        import time
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop()


if __name__ == "__main__":
    main()

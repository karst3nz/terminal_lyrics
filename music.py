import soundfile as sf
import sounddevice as sd

# music_ABSpath = "/home/karst3nz/Документы/PycharmProjects/terminal_lyrics/Heronwater — INTERLUDE BARS.flac"

def play_music(music_ABSpath):
    data, fs = sf.read(music_ABSpath)
    sd.play(data, fs)
    sd.wait()


if __name__ == "__main__":
    play_music()
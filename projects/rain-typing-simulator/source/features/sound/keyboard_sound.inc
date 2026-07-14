// 机械键盘音效生成与播放
// 本文件由 main.cpp 拆分而来，保持原有顺序以降低重构风险。

struct PlayingSample {
    WAVEHDR header{};
    std::vector<int16_t> data;
};

struct SoundEngine {
    HWAVEOUT out{};
    bool ready = false;
    std::vector<std::vector<int16_t>> samples;
};

static SoundEngine g_sound;

static void CALLBACK WaveOutCallback(HWAVEOUT wave, UINT msg, DWORD_PTR, DWORD_PTR param1, DWORD_PTR) {
    if (msg != WOM_DONE) return;
    auto* header = reinterpret_cast<WAVEHDR*>(param1);
    auto* sample = reinterpret_cast<PlayingSample*>(header->dwUser);
    waveOutUnprepareHeader(wave, header, sizeof(WAVEHDR));
    delete sample;
}

static std::vector<int16_t> MakeMechanicalSample(int seed) {
    constexpr int sampleRate = 44100;
    constexpr double duration = 0.058;
    const int samples = static_cast<int>(sampleRate * duration);
    std::mt19937 local(9000 + seed);
    std::uniform_real_distribution<double> noise(-1.0, 1.0);
    std::uniform_real_distribution<double> pitch(0.88, 1.16);
    std::uniform_real_distribution<double> body(0.82, 1.18);
    double p = pitch(local);
    double bodyScale = body(local);
    std::vector<int16_t> pcm;
    pcm.reserve(samples);

    for (int i = 0; i < samples; ++i) {
        double t = static_cast<double>(i) / sampleRate;
        double downEnv = std::exp(-t * 150.0);
        double releaseEnv = t > 0.014 ? 0.46 * std::exp(-(t - 0.014) * 110.0) : 0.0;
        double bodyEnv = std::exp(-t * 42.0);
        double highClick =
            std::sin(2 * 3.141592653589793 * (2300 * p) * t)
            + 0.55 * std::sin(2 * 3.141592653589793 * (4100 * p) * t)
            + 0.22 * std::sin(2 * 3.141592653589793 * (7600 * p) * t);
        double lowThock =
            0.70 * std::sin(2 * 3.141592653589793 * (145 * bodyScale) * t)
            + 0.34 * std::sin(2 * 3.141592653589793 * (260 * bodyScale) * t);
        double scratch = noise(local) * std::exp(-t * 180.0);
        double value = 8200.0 * ((downEnv + releaseEnv) * (0.58 * highClick + 0.42 * scratch)
            + 0.20 * bodyEnv * lowThock);
        value = std::max(-32767.0, std::min(32767.0, value));
        pcm.push_back(static_cast<int16_t>(value));
    }
    return pcm;
}

static void EnsureSoundEngine() {
    if (g_sound.ready) return;
    WAVEFORMATEX fmt{};
    fmt.wFormatTag = WAVE_FORMAT_PCM;
    fmt.nChannels = 1;
    fmt.nSamplesPerSec = 44100;
    fmt.wBitsPerSample = 16;
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample / 8;
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign;
    if (waveOutOpen(&g_sound.out, WAVE_MAPPER, &fmt, reinterpret_cast<DWORD_PTR>(WaveOutCallback), 0, CALLBACK_FUNCTION) != MMSYSERR_NOERROR) {
        return;
    }
    for (int i = 0; i < 12; ++i) {
        g_sound.samples.push_back(MakeMechanicalSample(i));
    }
    g_sound.ready = true;
}

static void PlayKeySound(const Settings& settings) {
    if (!settings.sound) return;
    EnsureSoundEngine();
    if (!g_sound.ready || g_sound.samples.empty()) return;
    std::uniform_int_distribution<size_t> pick(0, g_sound.samples.size() - 1);
    auto* play = new PlayingSample;
    play->data = g_sound.samples[pick(g_rng)];
    play->header.lpData = reinterpret_cast<LPSTR>(play->data.data());
    play->header.dwBufferLength = static_cast<DWORD>(play->data.size() * sizeof(int16_t));
    play->header.dwUser = reinterpret_cast<DWORD_PTR>(play);
    if (waveOutPrepareHeader(g_sound.out, &play->header, sizeof(WAVEHDR)) != MMSYSERR_NOERROR
        || waveOutWrite(g_sound.out, &play->header, sizeof(WAVEHDR)) != MMSYSERR_NOERROR) {
        waveOutUnprepareHeader(g_sound.out, &play->header, sizeof(WAVEHDR));
        delete play;
    }
}

"""
Air Cricket commentary: every line the umpire, the fielders and the commentary box can say,
and a generator that records them with Microsoft Edge's neural voices (edge-tts).

Make the clips (on a PC, or on an Android phone in Termux):

    pip install edge-tts
    python voice_lines.py

It writes air-cricket-voices.zip (about 1 MB). Unzip it into sounds/voice/ in the repo, or send it
to whoever builds the game; tools/build_page.py embeds every clip it finds there. Lines without a
clip are read by the device's own speech voice instead, so the game works either way.

Line ids are "key.n": the game asks for a key ("four") and picks one of its variants.
Odd-numbered variants use the first commentator's voice, even-numbered the second, so it sounds
like a commentary box. The "common" group (umpire calls and appeals) is the same in every language.
"""
import asyncio
import os
import shutil
import sys
import zipfile

VOICES = {
    # group: (first commentator, second commentator)
    "en": ("en-IN-PrabhatNeural", "en-IN-NeerjaNeural"),
    "hi": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
}
UMPIRE = ("en-IN-PrabhatNeural", "-5%", "+20%", "-2Hz")        # voice, rate, volume, pitch
APPEAL = ("en-AU-WilliamNeural", "+12%", "+30%", "+18Hz")

LINES = {
    "common": {
        "ump_noball.1": "No ball!",
        "ump_wide.1": "Wide!",
        "appeal.1": "Howzat!",
        "appeal.2": "How's that!",
    },
    "en": {
        "start.1": "Good evening, and welcome to Air Cricket under the lights. Here we go.",
        "start.2": "The field is set, the bowler's at the top of his mark. Let's play.",
        "start_daily.1": "It's the daily challenge. Everyone in the world faces these same balls today.",
        "start_super.1": "It's a Super Over! Six balls to decide it.",
        "four.1": "That's four! Cracking shot.",
        "four.2": "Into the gap, and that races away for four.",
        "four.3": "Beautifully timed. Four runs.",
        "four.4": "Too much width, and he puts it away. Four!",
        "edge_four.1": "Off the edge, and it runs away for four!",
        "six.1": "That's huge! Six!",
        "six.2": "Up, up and away. That's a maximum!",
        "six.3": "Into the stands! What a hit.",
        "six.4": "He's launched that! Six runs.",
        "six_big.1": "That's gone out of the ground!",
        "bowled.1": "Bowled him! The stumps are shattered.",
        "bowled.2": "Clean bowled! Straight through the gate.",
        "playedon.1": "Dragged on! He's played it onto his own stumps.",
        "caught.1": "Caught! He's picked out the fielder.",
        "caught.2": "In the air... and taken! He has to go.",
        "caught_behind.1": "Edged, and caught behind!",
        "cnb.1": "Caught and bowled! Sharp reflexes from the bowler.",
        "lbw.1": "Plumb in front! That's out, LBW.",
        "lbw.2": "Trapped in front. The finger goes up.",
        "notout_lbw.1": "Big appeal, but not out.",
        "notout_lbw.2": "The umpire's not interested.",
        "saved.1": "That would have been out, but it's a free hit!",
        "dropped.1": "Dropped! That's a life.",
        "dropped.2": "Oh, he's put it down! That should have been taken.",
        "beaten.1": "Beaten! Lovely delivery.",
        "beaten.2": "Past the outside edge.",
        "leave_good.1": "Well left.",
        "leave_good.2": "Good judgement, he lets that one go.",
        "leave_close.1": "Ooh, that was close to the stumps!",
        "helmet.1": "Ooh, that's hit him on the helmet!",
        "single.1": "They'll take a quick single.",
        "two.1": "Good running. They come back for two.",
        "free_hit.1": "Free hit coming up. Swing away!",
        "wide_call.1": "Too wide. That's called a wide.",
        "last_ball.1": "It all comes down to the last ball!",
        "need_one.1": "Just one needed to win.",
        "win.1": "And that's the winning hit! What a chase!",
        "win.2": "They've done it! Game over.",
        "lose.1": "That's the end of it. They fall short.",
        "tie.1": "Scores level! It's a tie!",
        "super_tie.1": "Level again! We'll need another Super Over.",
    },
    "hi": {
        "start.1": "नमस्कार, एयर क्रिकेट में आपका स्वागत है। फ्लडलाइट्स के नीचे, शुरू करते हैं।",
        "start.2": "फील्ड सज चुकी है, गेंदबाज़ तैयार है। चलिए खेलते हैं।",
        "start_daily.1": "आज का डेली चैलेंज। आज सबको यही गेंदें मिलेंगी।",
        "start_super.1": "सुपर ओवर! छह गेंदों में फ़ैसला होगा।",
        "four.1": "चौका! शानदार शॉट।",
        "four.2": "गैप में, और गेंद तेज़ी से सीमा रेखा के पार। चार रन!",
        "four.3": "क्या टाइमिंग है! चार रन।",
        "four.4": "जगह मिली, और बल्लेबाज़ ने छोड़ा नहीं। चौका!",
        "edge_four.1": "किनारा लगा, और गेंद चार रन के लिए निकल गई!",
        "six.1": "बहुत बड़ा शॉट! छक्का!",
        "six.2": "ऊपर, और ऊपर... ये गया छक्का!",
        "six.3": "सीधे स्टैंड्स में! क्या हिट है।",
        "six.4": "हवा में उठा दिया! छह रन।",
        "six_big.1": "ये तो स्टेडियम के बाहर चला गया!",
        "bowled.1": "बोल्ड! स्टंप्स बिखर गए।",
        "bowled.2": "क्लीन बोल्ड! बल्ले और पैड के बीच से।",
        "playedon.1": "अंदरूनी किनारा, और गेंद स्टंप्स पर जा लगी!",
        "caught.1": "कैच! सीधा फील्डर के हाथ में।",
        "caught.2": "हवा में... और लपक लिया! आउट।",
        "caught_behind.1": "किनारा लगा, और विकेटकीपर ने कैच पकड़ लिया!",
        "cnb.1": "कॉट एंड बोल्ड! गेंदबाज़ की शानदार फुर्ती।",
        "lbw.1": "सीधे सामने! एल बी डब्ल्यू, आउट।",
        "lbw.2": "पैड पर लगी, और अंपायर ने उंगली उठा दी।",
        "notout_lbw.1": "ज़ोरदार अपील, लेकिन नॉट आउट।",
        "notout_lbw.2": "अंपायर ने अपील ठुकरा दी।",
        "saved.1": "आउट हो जाते, लेकिन ये फ्री हिट है!",
        "dropped.1": "कैच छूट गया! बल्लेबाज़ को जीवनदान।",
        "dropped.2": "अरे, ये तो पकड़ना चाहिए था!",
        "beaten.1": "बीट! कमाल की गेंद।",
        "beaten.2": "बाहरी किनारे के पास से निकल गई।",
        "leave_good.1": "अच्छा छोड़ा।",
        "leave_good.2": "समझदारी से छोड़ दी गेंद।",
        "leave_close.1": "ओह, स्टंप्स के बहुत करीब से!",
        "helmet.1": "ओह, गेंद सीधे हेलमेट पर लगी!",
        "single.1": "जल्दी से एक रन।",
        "two.1": "बढ़िया दौड़, दो रन पूरे।",
        "free_hit.1": "फ्री हिट! अब खुलकर खेलिए।",
        "wide_call.1": "बहुत बाहर। वाइड बॉल।",
        "last_ball.1": "सब कुछ आख़िरी गेंद पर!",
        "need_one.1": "जीत के लिए बस एक रन चाहिए।",
        "win.1": "और ये रहा जीत का शॉट! क्या चेज़ है!",
        "win.2": "कर दिखाया! मैच ख़त्म।",
        "lose.1": "बस, यहीं ख़त्म। लक्ष्य से पीछे रह गए।",
        "tie.1": "स्कोर बराबर! मैच टाई!",
        "super_tie.1": "फिर से बराबर! एक और सुपर ओवर होगा।",
    },
}


def voice_for(group, line_id):
    if line_id.startswith("ump_"):
        return UMPIRE
    if line_id.startswith("appeal"):
        return APPEAL
    first, second = VOICES[group]
    n = int(line_id.rsplit(".", 1)[1])
    return (first if n % 2 else second, "+6%", "+0%", "+0Hz")


async def record(edge_tts, sem, group, line_id, text, out_dir):
    path = os.path.join(out_dir, group, line_id + ".mp3")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path, None
    voice, rate, volume, pitch = voice_for(group, line_id)
    err = None
    async with sem:
        for attempt in range(3):
            try:
                await edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch).save(path)
                if os.path.getsize(path) > 0:
                    return path, None
                err = RuntimeError("empty file")
            except Exception as e:  # network blips: try again
                err = e
            await asyncio.sleep(1.5 * (attempt + 1))
        return path, err


async def main():
    try:
        import edge_tts
    except ImportError:
        sys.exit("edge-tts is not installed. Run:  pip install edge-tts")
    out_dir = "air-cricket-voices"
    for g in LINES:
        os.makedirs(os.path.join(out_dir, g), exist_ok=True)
    sem = asyncio.Semaphore(4)
    jobs = [record(edge_tts, sem, g, i, t, out_dir) for g, lines in LINES.items() for i, t in lines.items()]
    done, failed = 0, []
    for coro in asyncio.as_completed(jobs):
        path, err = await coro
        if err:
            failed.append((path, err))
        else:
            done += 1
            print(f"  {done:3d}  {path}")
    zpath = "air-cricket-voices.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for g in LINES:
            for f in sorted(os.listdir(os.path.join(out_dir, g))):
                z.write(os.path.join(out_dir, g, f), f"{g}/{f}")
    print(f"\nRecorded {done} of {done + len(failed)} lines -> {os.path.abspath(zpath)}")
    for path, err in failed:
        print("  failed:", path, err)
    downloads = os.path.expanduser("~/storage/downloads")      # Termux with storage access
    if os.path.isdir(downloads):
        shutil.copy(zpath, downloads)
        print("Copied to your phone's Downloads folder.")
    if failed:
        print("Run the script again to retry the failed lines; finished ones are kept.")


if __name__ == "__main__":
    asyncio.run(main())

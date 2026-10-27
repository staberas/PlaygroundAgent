"""Deterministic, non-destructive destination suggestions from cached CSV detections.

No inference, file operations, or image moves. Paths are relative labels only.
"""
import json
from pathlib import Path

CATEGORIES = ("Cosplay", "General", "Anime", "Meme")

def load(row, field):
    try:
        value = json.loads(row.get(field) or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}

def clamp(value):
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0

def classify(row, cosplay_force_nsfw=False):
    wolf = load(row, "smilingwolf")
    marqo = load(row, "marqo")
    nsfw = load(row, "nsfw")
    nude = load(row, "nude") or load(row, "nudenet")
    ratings = wolf.get("ratings") or {}
    tags = {x["tag"].lower(): clamp(x.get("score")) for x in wolf.get("general_tags", [])
            if isinstance(x, dict) and isinstance(x.get("tag"), str)}
    def tag(*names):
        return max([tags.get(name, 0) for name in names] or [0])

    m = clamp(marqo.get("NSFW"))
    porn = max(clamp(nsfw.get("porn")), clamp(nsfw.get("hentai")))
    sexy = clamp(nsfw.get("sexy"))
    explicit = clamp(ratings.get("explicit"))
    questionable = clamp(ratings.get("questionable"))
    sensitive = clamp(ratings.get("sensitive"))
    exposed = bool(nude.get("nude"))
    # Sexually explicit anatomical tags should not be triggered by a generic 'breasts' tag.
    anatomy = tag("nipples", "pussy", "penis", "sex", "vaginal", "anal", "nude")

    # Explicit signals outweigh general skin or Marqo alone.
    strong = (explicit >= .65 or porn >= .78 or exposed or
              (questionable >= .68 and anatomy >= .65) or
              (m >= .90 and (questionable >= .65 or porn >= .4)))
    nsfw_score = min(1., .32*m + .28*max(explicit, questionable) +
                     .22*porn + .18*anatomy + (.26 if exposed else 0))
    moderate = ((m >= .8 and max(questionable, sensitive) >= .72) or
                (questionable >= .7 and anatomy >= .5) or
                (porn >= .5 and m >= .6))
    risky = strong or moderate or nsfw_score >= .67
    # Default borderline results to SFW but flag for human verification.
    disagreement = ((m >= .7 and clamp(ratings.get("general")) >= .7) or
                    (m < .3 and (explicit >= .65 or questionable >= .8)))
    ambiguous = (not strong and (.42 <= nsfw_score < .67 or disagreement or moderate))
    top = "NSFW" if risky else "SFW"

    scores = {name:0.0 for name in CATEGORIES}
    # Real cosplay photography, explicitly tagged. Anime character costumes
    # alone should not qualify as cosplay.
    scores["Cosplay"] = (2.6*tag("cosplay", "cosplayer", "costume", "real_life") +
                         1.3*tag("photo_(medium)", "photo", "photorealistic", "live_action") +
                         .65*tag("realistic") + .5*tag("wig") + .3*tag("mask"))
    # Text-centric comics, jokes, screenshots and reaction images.
    scores["Meme"] = (2.3*tag("meme", "reaction_image", "demotivational_poster", "image_macro") +
                      1.1*tag("fake_screenshot", "screenshot", "comic", "4koma") +
                      .9*tag("text_focus", "english_text", "speech_bubble") +
                      .45*tag("no_humans"))
    scores["Anime"] = (1.55*tag("anime", "anime_screencap", "anime_coloring", "manga", "2d") +
                       .8*tag("virtual_youtuber", "character", "cel_shading") +
                       .5*tag("1girl", "1boy", "multiple_girls", "multiple_boys") +
                       .5*tag("colored_skin", "blue_skin", "animal_ears"))
    # If there's no evidence for a specialist folder, choose General.
    scores["General"] = .85 + .4*tag("scenery", "landscape", "nature", "traditional_media",
                                      "still_life", "realistic", "no_humans")
    # WD Tagger v3 mostly produces content tags, not explicit "anime"/
    # "illustration" labels. Use multiple independent indicators.
    # Legacy NSFWJS 'hentai' is an art-style signal, NOT proof of NSFW.
    hentai = clamp(nsfw.get("hentai"))
    illustration_evidence = max(
        tag("anime_screencap", "anime_coloring", "manga", "lineart",
            "illustration", "sketch", "2d", "cel_shading"),
        .75 * tag("virtual_youtuber", "chibi", "anime", "manga"),
        .68 * tag("colored_skin", "blue_skin"),
        .6 * tag("animal_ears", "cat_ears", "ahoge"),
        .72 * hentai,
    )
    photo_evidence = max(
        tag("photo_(medium)", "photography_(artwork)", "real_life",
            "photorealistic", "live_action", "cosplay", "cosplayer"),
        .6 * clamp(nsfw.get("porn")) if hentai < .20 else 0.0,
    )
    costume_evidence = max(
        tag("cosplay", "cosplayer", "costume"),
        .65 * tag("wig", "latex_bodysuit", "bodysuit", "leotard", "uniform", "mask"),
    )
    # Full-costume photography is more important than anime-themed props.
    photo_cosplay = (tag("cosplay", "cosplayer") >= .35 or
                    (photo_evidence >= .35 and costume_evidence >= .35))
    looks_drawn = (illustration_evidence >= .38 or
                   (hentai >= .30 and hentai > clamp(nsfw.get("porn"))))
    meme_signal = scores["Meme"] >= 1.7 and scores["Meme"] >= scores["Anime"]
    if photo_cosplay:
        category = "Cosplay"
    elif meme_signal:
        category = "Meme"
    elif looks_drawn and (hentai >= .30 or photo_evidence < .55):
        category = "Anime"
    else:
        category = "General"
    if cosplay_force_nsfw and category == "Cosplay":
        top = "NSFW"
    if not (wolf or marqo or nsfw or nude):
        return {"destination_folder":"Review/Unclassified","route_review":"yes",
                "route_reason":"No classification outputs","route_confidence":0.0}
    reasons = [f"Marqo {m:.2f}", f"Wolf E/Q {explicit:.2f}/{questionable:.2f}",
               f"Legacy explicit {porn:.2f}", f"anatomy {'yes' if exposed else 'no'}"]
    if disagreement: reasons.append("classifier disagreement")
    if ambiguous: reasons.append("borderline NSFW evidence")
    medium_uncertain = (category == "General" and scores["Anime"] > .75)
    if medium_uncertain:
        reasons.append("image medium uncertain (photo vs illustration)")
    if photo_cosplay:
        reasons.append("photo + costume evidence")
    if cosplay_force_nsfw and category == "Cosplay":
        reasons.append("cosplay NSFW override enabled")
    needs_review = ambiguous or disagreement or medium_uncertain or (cosplay_force_nsfw and category == "Cosplay")
    confidence = round(min(1., abs(nsfw_score - .55)*1.3 +
                           max(0., scores[category] - sorted(scores.values())[-2])*.1), 3)
    return {"destination_folder":f"{top}/{category}",
            "route_review":"yes" if needs_review else "no",
            "route_reason":"; ".join(reasons),
            "route_confidence":confidence}

def assign(csv_path, force=False):
    from pipeline import ROOT
    config_path = ROOT / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    cosplay_force_nsfw = bool(config.get("settings", {}).get("cosplay_force_nsfw", False))
    from pipeline import read_rows, write_rows
    rows, columns = read_rows(csv_path)
    for col in ("destination_folder", "route_review", "route_confidence", "route_reason"):
        if col not in columns: columns.append(col)
    count=0
    for row in rows:
        if str(row.get("ignore", "")).lower() in ("yes","true","1"):
            continue
        if row.get("destination_folder") and not force:
            continue
        row.update(classify(row, cosplay_force_nsfw=cosplay_force_nsfw))
        count += 1
    write_rows(csv_path, rows, columns)
    return count

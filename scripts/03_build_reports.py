"""
Hand-encode the 49 Dawei Watch posts of 26-29 Sep 2026 into structured data and
geocode every named place against MIMU.

Source: Dawei Watch Facebook page (https://web.facebook.com/DaweiWatch), posts
collected by the user into dawei_flood.docx, newest first. Copied to
data/source/dawei_watch_2026-09-26_29.txt with one paragraph per line; every
`line` below is a line number in that file, so each figure traces back to the text.
The post a line belongs to is worked out from the file itself (each post starts
with a headline followed by a "Dawei Watch | <date>" line).

Model
  SITES      one record per place. `reports` lists what each post said about it,
             in the order written; the post fixes the day. A site's state on a day
             (severity, figures, red-level flag, rescue access) is built from the
             reports published up to that day, so the map can step 26 -> 27 -> 28 -> 29.
  INCIDENTS  roads, bridges and slides that are not villages, also dated.
  RESCUE     the rescue convoy's progress south into Launglon.
  TIMELINE   events by the time they happened (not when they were posted).
  QUOTES     residents and responders, Myanmar original plus a close translation.

Severity of a report (ordinal) -- what happened to people there
  fatal     deaths or missing people reported
  severe    houses buried or submerged to the roof, people trapped, a whole
            village under water, or a red-level designation
  affected  named as flooded or hit by landslides, no further detail
A site's severity on a day is the highest of its reports so far: later reports add
detail, they do not make an earlier disaster smaller.

Geocoding grades (`match`), by Myanmar-script name (VLG_MMR) within the township:
  exact     MIMU has the name as written
  variant   MIMU spells it differently or files it under the next township
  probable  best candidate, not certain
  approx    not in MIMU; placed at a stated reference
  unlocated not in MIMU and no defensible position; listed, not mapped
"""

import bisect
import json
import os
import re
import warnings

import geopandas as gpd
from shapely.geometry import Point

warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
SRC = os.path.join(HERE, "..", "data", "source", "dawei_watch_2026-09-26_29.txt")
OUT = os.path.join(HERE, "..", "data", "processed", "flood.json")
DAYS = [26, 27, 28, 29]

# ---------------------------------------------------------------------------
# Posts, oldest first. `h` is the headline's line number; `as_of` is the latest
# time the post's own text refers to.
# ---------------------------------------------------------------------------
POSTS = [
    dict(h=741, day=26, as_of="26 Sep, 6 pm", kind="Breaking news",
         en="Landslide at Kyauk Ni Maw, Launglon, buries people and houses; emergency rescue needed"),
    dict(h=723, day=26, as_of="26 Sep, night",
         en="Floods and landslides in Launglon; families move out overnight"),
    dict(h=711, day=27, as_of="27 Sep, 9:30 am",
         en="Floods and landslides in Launglon Township; emergency help needed"),
    dict(h=680, day=27, as_of="27 Sep, morning", kind="Round-up",
         en="Floods and landslides in Dawei District, township by township"),
    dict(h=658, day=27, as_of="27 Sep, late morning",
         en="About 20 villages flooded in Launglon, hills collapse, at least two missing including a child"),
    dict(h=651, day=27, as_of="27 Sep, midday",
         en="Kadet Nge [Htein] landslide: about 10 missing, bodies of a child and a woman found"),
    dict(h=645, day=27, as_of="27 Sep, midday",
         en="Min Yat landslide buries mother and child; mother dies, rescuers still working to free the child"),
    dict(h=632, day=27, as_of="27 Sep",
         en="Flooded Thayetchaung Township needs emergency rescue"),
    dict(h=621, day=27, as_of="27 Sep, 12 noon",
         en="Landslides continue on Launglon's western hills"),
    dict(h=612, day=27, as_of="27 Sep",
         en="Landslide at Kayin Gyi, Launglon, buries nearly 30 houses"),
    dict(h=602, day=27, as_of="27 Sep",
         en="Today's rain at Dawei sets an all-time record"),
    dict(h=593, day=27, as_of="27 Sep, 3:30 pm",
         en="Floods on the Dawei–Myeik road: some vehicles turn back, others stranded"),
    dict(h=540, day=27, as_of="27 Sep, 2:30 pm", kind="Round-up",
         en="Floods and landslides bring a sea of suffering to the Dawei region"),
    dict(h=527, day=27, as_of="27 Sep, 4:30 pm",
         en="More landslides near Launglon; search-and-rescue teams cannot advance"),
    dict(h=511, day=27, as_of="27 Sep",
         en="Dozens of villages flooded in Thayetchaung; buffalo and cattle killed"),
    dict(h=500, day=27, as_of="27 Sep, evening",
         en="Streams overflow across Dawei town; power cut to the whole town"),
    dict(h=487, day=28, as_of="28 Sep, morning",
         en="Single-storey houses under water in Dawei town wards"),
    dict(h=473, day=28, as_of="28 Sep",
         en="Thayetchaung needs emergency help"),
    dict(h=437, day=28, as_of="27 Sep, late", kind="Explainer",
         en="Record Dawei rain and a sudden disaster",
         note="Dated 27 Sep in its text; posted among the 28 Sep updates."),
    dict(h=426, day=28, as_of="28 Sep",
         en="Whole village of Pa Kar Ri on the Dawei–Htee Khee road under water; low houses submerged"),
    dict(h=414, day=28, as_of="28 Sep, morning",
         en="Another landslide at Kayin Gyi, Launglon; the east side of the village destroyed"),
    dict(h=404, day=28, as_of="28 Sep",
         en="Tanintharyi River and streams rise; villages begin to flood"),
    dict(h=392, day=28, as_of="28 Sep, 12 noon",
         en="Advance rescue team reaches Kadet Nge Htein, where dozens are missing; search begins"),
    dict(h=384, day=28, as_of="28 Sep, morning",
         en="Landslide at Nyaw Pyin, Launglon, kills two women"),
    # ---- added with the 29 Sep update: later 28 Sep posts, then 29 Sep
    dict(h=369, day=28, as_of="28 Sep, evening",
         en="Water falls in Launglon town and some villages; seven cattle swept away at Way Di saved"),
    dict(h=362, day=28, as_of="28 Sep",
         en="Landslides at Pa Nyit, Launglon, cut off villages beyond it"),
    dict(h=350, day=28, as_of="28 Sep, evening",
         en="Dawei sets another rainfall record today"),
    dict(h=293, day=28, as_of="28 Sep, evening", kind="Feature",
         en="What Thayetchaung is going through"),
    dict(h=284, day=28, as_of="28 Sep, evening",
         en="Landslide kills a mother and son at Ka Det Gyi, Launglon"),
    dict(h=272, day=28, as_of="28 Sep, evening",
         en="More than 600 flood victims in Dawei town need food, clothes and medicine"),
    dict(h=260, day=28, as_of="28 Sep, evening",
         en="Three more bodies found at Kadet Nge Htein; five dead there"),
    dict(h=188, day=28, as_of="28 Sep, afternoon", kind="Explainer",
         en="Help falls short and rescuers can't get through in the Dawei disaster zone"),
    dict(h=185, day=28, as_of="28 Sep", kind="Video",
         en="Advance rescue team reaches Kadet Nge Htein, where dozens are missing"),
    dict(h=177, day=28, as_of="28 Sep, evening",
         en="River rises into Lay Hnya village, Bokpyin: roads and houses begin to flood"),
    dict(h=146, day=28, as_of="28 Sep", kind="Interview",
         en="The people standing up to the Dawei flood and landslide disaster"),
    dict(h=134, day=28, as_of="28 Sep, evening",
         en="Thayetchaung flood deaths reach six; two more swept away"),
    dict(h=125, day=28, as_of="28 Sep, night",
         en="Kyauk Ni Maw landslide buries about 50 houses; at least five missing"),
    dict(h=116, day=29, as_of="29 Sep, morning",
         en="Mother and son still missing at Tha Byar, Launglon"),
    dict(h=108, day=29, as_of="29 Sep, midday", kind="Photo story",
         en="Water recedes in Dawei town"),
    dict(h=91, day=29, as_of="28 Sep, night", kind="Interview",
         en="Nyaw Pyin, knocked down again and again, needs help to get back up",
         note="Interview recorded on the night of 28 Sep; posted on 29 Sep."),
    dict(h=81, day=29, as_of="29 Sep",
         en="Inwa hill slide at Thea Pon, Launglon, wrecks a monastery and orchards"),
    dict(h=71, day=29, as_of="29 Sep",
         en="Tanintharyi River keeps rising: residents move out as 20+ villages go under"),
    dict(h=57, day=29, as_of="29 Sep, midday", kind="Round-up",
         en="Disaster deaths in the Dawei region pass 20"),
    dict(h=47, day=29, as_of="29 Sep, 3 pm",
         en="Tanintharyi River passes 26 ft, above its danger mark"),
    dict(h=35, day=29, as_of="29 Sep",
         en="Water falls in Thayetchaung, but power cuts keep phones down"),
    dict(h=17, day=29, as_of="29 Sep", kind="Interview",
         en="Kyauk Ni Maw, still cut off among the slides and the wreckage"),
    dict(h=7, day=29, as_of="29 Sep",
         en="Ti Zit, trapped by landslides, needs food"),
    dict(h=4, day=29, as_of="29 Sep", kind="Video",
         en="Water falls in Thayetchaung; power cut makes contact hard"),
    dict(h=1, day=29, as_of="29 Sep", kind="Video",
         en="Mother and son still missing at Tha Byar, a Launglon landslide village"),
]


def R(line, sev, text, **kw):
    return dict(line=line, sev=sev, text=text, **kw)


LIST27 = ("Named among villages hit by floods and landslides between Ka Myaw Gyi, at the "
          "Dawei–Launglon boundary, and Kyauk Ni Maw.")

# ---------------------------------------------------------------------------
# Sites
# roles: relief (camp/shelter) | needs (aid requested) | access (road/bridge cut)
#        | comms (contact lost) | observe (observation only) | school
#        | receding (the water is reported falling)
# rescue: "reached" | "not-reached"
# ---------------------------------------------------------------------------
SITES = [
    # ================================================== Launglon, north of town
    dict(id="ka-myaw-gyi", mm="ကမြောကြီး", en="Ka Myaw Gyi", ts="Launglon", area="Launglon north",
         hazard="both", reports=[
             R(663, "affected", LIST27),
             R(675, "affected", "Floods and landslides: vehicles barred from Ka Myaw Gyi onward.", roles=["access"]),
             R(716, "affected", "Rescue teams heading for southern Launglon were held up by flooding at "
                                "Ka Myaw Gyi on the morning of 27 Sep.", roles=["access"]),
         ]),
    dict(id="inn-wun", mm="အင်းဝန်း", en="Inn Wun", ts="Launglon", area="Launglon north", hazard="flood",
         reports=[
             R(663, "affected", LIST27),
             R(673, "affected", "Near the Dawei River; residents say the water is waist-deep.", depth_ft=3),
         ]),
    dict(id="min-yat", mm="မင်းရပ်", en="Min Yat", ts="Launglon", area="Launglon north", hazard="both",
         reports=[
             R(629, "severe", "Many houses buried by landslides."),
             R(647, "fatal", "A slide in Min Yat Chaung, west of the village, buried a mother and her child in "
                             "their house. Rescuers found the mother's body and the child alive; rescue "
                             "vehicles could not get into the valley.", dead=1, rescued=1),
             R(674, "fatal", "The hill stream overflowed and flooded the village."),
             R(558, "fatal", "The child was found alive and rescuers carried on working."),
         ]),
    dict(id="way-di", mm="ဝေဒီ", en="Way Di", ts="Launglon", area="Launglon north", hazard="both",
         reports=[R(663, "affected", LIST27)]),
    dict(id="tha-byar", mm="သဗျာ", en="Tha Byar", ts="Launglon", area="Launglon north", hazard="both",
         reports=[
             R(667, "severe", "Hillsides collapsed; low-lying parts under water a person's height deep. People "
                              "have been trapped on their houses since the night, and some are said to be "
                              "missing.", depth_ft=6),
             R(624, "severe", "Search-and-rescue teams reached Tha Byar at about 11 am on 27 Sep and cleared "
                              "earth and rocks from the road by the monastery.", rescue="reached",
               roles=["access"]),
             R(629, "severe", "Many houses buried by landslides."),
         ]),
    dict(id="pyin-sa-thi-maw", mm="ပဉ္စသီမော်", en="Pyin Sa Thi Maw", ts="Launglon", area="Launglon north",
         hazard="landslide", reports=[
             R(625, "affected", "Landslide debris across the road at the village exit, cleared by rescue teams "
                                "on 27 Sep.", roles=["access"]),
         ]),
    dict(id="thea-pon", mm="သဲပုံ", en="Thea Pon", ts="Launglon", area="Launglon north", hazard="landslide",
         reports=[
             R(679, "affected", "Landslide on the road up Inwa hill."),
             R(560, "affected", "A slide on Inwa hill buried land and destroyed orchards."),
         ]),
    dict(id="sit-pyay", mm="စစ်ပြဲ", en="Sit Pyay", ts="Launglon", area="Launglon north", hazard="flood",
         reports=[
             R(730, "affected", "The whole village under water on the night of 26 Sep; belongings under the "
                                "houses washed away. Residents stayed awake for fear of landslides."),
         ]),

    # ================================================== Launglon town
    dict(id="launglon-town", mm="လောင်းလုံးမြို့", en="Launglon town", ts="Launglon", area="Launglon town",
         town="Launglon", hazard="both", reports=[
             R(725, "affected", "Roads overtopped and water in houses across Launglon; families in low-lying "
                                "homes moved out in the night. Village roads and bridges are under water.",
               roles=["access"]),
             R(660, "affected", "The town and about 20 villages in the south of the township are flooded."),
             R(529, "affected", "Rescue teams are stuck in Launglon town: the Poe Zar Pin slide blocks the road "
                                "south.", roles=["access"]),
             R(421, "affected", "More than 20 villages in the township are flooded. Most residents are in "
                               "relief camps and monasteries; food has run out.", roles=["relief", "needs"]),
         ]),

    # ================================================== Launglon, south of town
    dict(id="nyin-maw", mm="ညင်းမော်", en="Nyin Maw", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(663, "affected", LIST27),
             R(539, "affected", "Photo of the village's condition on 27 Sep. The Poe Zar Pin slide lies on the "
                                "road between here and Launglon town."),
         ]),
    dict(id="ka-htaung-ni", mm="ကထောင်းနီ", en="Ka Htaung Ni", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(663, "affected", LIST27)]),
    dict(id="ka-nyon-kyun", mm="ကညုံကျွန်း", en="Ka Nyon Kyun", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(663, "affected", LIST27)]),
    dict(id="gawt-inn", mm="ဂေါ့အင်း", en="Gawt Inn", ts="Launglon", area="Launglon south", hazard="both",
         reports=[R(663, "affected", LIST27)]),
    dict(id="auk-yay-phyu", mm="အောက်ရေဖြူ", en="Auk Yay Phyu", ts="Launglon", area="Launglon south",
         hazard="both", alias_mm="ရေဖြူ",
         match_note="The 27 Sep posts call it ရေဖြူ (Yay Phyu); the 28 Sep post names it အောက်ရေဖြူ, "
                    "MIMU's village 1.6 km from Kadet Nge Htein.",
         reports=[
             R(663, "affected", LIST27),
             R(657, "affected", "Some Kadet Nge [Htein] residents have moved here, a little over a mile away.",
               roles=["relief"]),
             R(563, "severe", "An emergency camp at the village school and on the pagoda hill shelters about "
                              "500 flood victims, who need help.", sheltering=500, roles=["relief", "needs", "school"]),
             R(389, "severe", "As of 28 Sep the rescue team from Dawei had got no further south than Auk Yay "
                            "Phyu.", rescue="reached"),
         ]),
    dict(id="ka-det-gyi", mm="ကဒက်ကြီး", en="Ka Det Gyi", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(735, "affected", "People living near the hills have packed their belongings; some are moving out."),
             R(663, "affected", LIST27),
         ]),
    # Several posts call it ကဒက်ငယ် (Ka Det Nge), once ကဒက်ငယ်ကြီး; local residents confirmed that this is Ka Det
    # Nge Htein, so those reports are here. Figures are read, never summed, across reports (see main()), so
    # the two bodies and "about 10 missing" of 27 Sep are not counted again on top of this village's own.
    dict(id="ka-det-nge-htein", mm="ကဒက်ငယ်ထိန်", en="Ka Det Nge Htein", ts="Launglon",
         area="Launglon south", hazard="landslide", alias_mm="ကဒက်ငယ် · ကဒက်ငယ်ကြီး",
         merge_note="Some posts call it ကဒက်ငယ် (Ka Det Nge), and the 9:30 am post of 27 Sep ကဒက်ငယ်ကြီး (Ka Det Nge "
                    "Gyi). Local residents confirmed these are Ka Det Nge Htein, so those reports are merged here "
                    "and its figures are not counted twice.",
         reports=[
             R(719, "severe", "Designated red level (as Kadet Nge Gyi). Rescue teams had not reached it by 9:30 am on "
                              "27 Sep.", red=True, rescue="not-reached"),
             R(663, "severe", LIST27),
             R(653, "fatal", "About 10 residents buried in their houses by the landslide. The bodies of a child "
                             "and a woman have been found; villagers are searching for the rest themselves.",
               dead=2, missing=10),
             R(672, "fatal", "Photos show waist-deep water in the village.", depth_ft=3),
             R(554, "fatal", "Heavy loss of life and property; tens of people missing, about 10 still "
                             "missing after two bodies were recovered."),
             R(422, "fatal", "Among the villages with deaths; red level.", red=True),
             R(424, "fatal", "Rescue teams from Dawei had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
             R(671, "severe", "Landslides and flooding."),
             R(536, "fatal", "By the evening of 27 Sep dozens were missing and two bodies had been found.",
               dead=2, missing_text="dozens"),
             R(562, "fatal", "The hill beside the village collapsed, burying at least 50 houses. Dozens of "
                             "people are missing.", houses=50),
             R(397, "fatal", "An advance rescue team, bypassing the blocked road on foot through the forest, "
                            "reached the village at about 8 am on 28 Sep and began searching.",
               rescue="reached"),
             R(400, "fatal", "Red level. Three bodies recovered by 28 Sep; dozens of residents still missing.",
               dead=3, red=True),
         ]),
    dict(id="ka-det-nge-seik", mm="ကဒက်ငယ်ဆိပ်", en="Ka Det Nge Seik", ts="Launglon", area="Launglon south",
         hazard="both", reports=[
             R(715, "severe", "Landslides, and serious flooding in low-lying parts."),
             R(719, "severe", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(563, "severe", "Cut off by broken roads; needs food and drinking water.", roles=["needs", "access"]),
         ]),
    dict(id="taw-kye", mm="တောကျဲ", en="Taw Kye", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(663, "affected", LIST27),
             R(388, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="tha-pyay-shaung", mm="သပြေရှောင်", en="Tha Pyay Shaung", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(663, "affected", LIST27)]),
    dict(id="tha-kyet-taw", mm="သကျက်တော", en="Tha Kyet Taw", ts="Launglon", area="Launglon south",
         hazard="both", reports=[
             R(663, "affected", LIST27),
             R(715, "affected", "Landslides, and flooding in low-lying parts."),
             R(388, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="ra-be", mm="ရဘဲ", en="Ra Be", ts="Launglon", area="Launglon south", hazard="landslide",
         vt_hint="Tha Kyet Taw", reports=[
             R(388, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="za-lut", mm="ဇလွတ်", en="Za Lut", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(663, "affected", LIST27),
             R(715, "affected", "Landslides, and flooding in low-lying parts."),
             R(537, "fatal", "People dead and missing in floods and landslides, residents say."),
             R(424, "fatal", "Rescue teams had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
             R(388, "fatal", "No relief has arrived.", roles=["needs"]),
         ]),
    dict(id="za-lut-pyin-gyi", mm="ဇလွတ်ပြင်ကြီး", en="Za Lut Pyin Gyi", ts="Launglon",
         area="Launglon south", hazard="landslide", mimu_mm="ပြင်ကြီး", vt_hint="Za Lut", match="probable",
         match_note="Taken as MIMU's ပြင်ကြီး (Pyin Gyi) in Za Lut village tract. It may be the same place as "
                    "Za Lut itself.",
         reports=[
             R(401, "fatal", "Designated red level for floods and landslides.", red=True),
             R(422, "fatal", "Among the villages with deaths.", ),
         ]),
    dict(id="ti-zit", mm="တီဇစ်", en="Ti Zit", ts="Launglon", area="Launglon south", hazard="landslide",
         reports=[
             R(538, "severe", "A landslide destroyed orchards and some houses; residents are trapped."),
             R(401, "fatal", "Designated red level; deaths reported and some residents still missing.", red=True),
             R(424, "fatal", "Rescue teams had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
         ]),
    dict(id="kyauk-ni-maw", mm="ကျောက်နီမော်", en="Kyauk Ni Maw", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(743, "fatal", "A village between the hills and the sea. A landslide on the evening of 26 Sep "
                             "buried people and houses. Residents pulled out an elderly person and two "
                             "children; others are missing and the ground was still moving at 6 pm.",
               rescued=3, missing_text="some"),
             R(731, "fatal", "Needs emergency rescue."),
             R(719, "fatal", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(664, "fatal", "Slides since about 5 pm on 26 Sep are still coming down. A child and a man are "
                             "missing; no rescue is possible yet. The road to Shin Maw is destroyed.",
               missing=2, roles=["access"]),
             R(670, "fatal", "Contact with the village was lost from the morning of 27 Sep.", roles=["comms"]),
             R(422, "fatal", "Among the villages with deaths; red level.", red=True),
         ]),
    dict(id="nyaw-pyin", mm="ညောပြင်", en="Nyaw Pyin", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(669, "severe", "Landslides."),
             R(719, "severe", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(561, "severe", "Deaths reported but not confirmed."),
             R(537, "fatal", "People dead and missing, residents say."),
             R(386, "fatal", "A landslide at Thayet Pin Kone (Shit Pan Gu) on 27 Sep killed two women, one of "
                           "them elderly. The village, already hit by the war, is short of food and drinking "
                           "water, and no relief has arrived. Contact was lost on the morning of 28 Sep.",
               dead=2, roles=["needs", "comms"], rescue="not-reached"),
         ]),

    # ================================================== Launglon, north-west coast
    dict(id="tha-bawt-seik", mm="သဘော့ဆိပ်", en="Tha Bawt Seik", ts="Launglon", area="Launglon north-west",
         hazard="both", reports=[
             R(547, "affected", "Near Maungmagan beach; named among villages hit by floods and landslides."),
         ]),
    dict(id="kayin-gyi", mm="ကရင်ကြီး", en="Kayin Gyi", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(614, "severe", "The hills east of the village collapsed at about 9 pm on 26 Sep and 2 am on "
                              "27 Sep, burying nearly 30 houses, two-wheel tractors and motorcycles. No one was "
                              "hurt. About 30 households, some 60 people, moved to the monastery and need help.",
               houses=30, sheltering=60, roles=["relief", "needs"]),
             R(565, "severe", "About 30 houses buried; more than 60 people moved to the monastery."),
             R(416, "severe", "Another slide on the night of 27 Sep covered the whole eastern half of the "
                             "village, destroying houses, the bridge and the village roads. Residents are "
                             "living at the monastery and urgently need food.",
               houses_text="east half of village", roles=["access", "relief", "needs"]),
         ]),
    dict(id="maungmagan", mm="မောင်းမကန်", en="Maungmagan", ts="Launglon", area="Launglon north-west",
         hazard="flood", reports=[
             R(568, "affected", "The blue-green sea at Maungmagan and nearby beaches turned muddy yellow.",
               roles=["observe"]),
         ]),
    dict(id="kyet-hlut", mm="ကြက်လွတ်", en="Kyet Hlut", ts="Launglon", area="Launglon south",
         hazard="landslide", mimu_mm="ကြက်လွှတ်", match="variant",
         match_note="MIMU spells it ကြက်လွှတ် (Kyet Hlut), in Kyauk Mat Tat village tract.",
         reports=[
             R(661, "affected", "Hills have been collapsing since the evening of 25 Sep as far as Kyet Lut; no "
                                "rescue has been possible."),
         ]),

    # ================================================== Thayetchaung
    dict(id="thayetchaung-town", mm="သရက်ချောင်းမြို့", en="Thayetchaung town", ts="Thayetchaung",
         area="Thayetchaung", town="Thayetchaung", hazard="flood", reports=[
             R(694, "severe", "Water about 6 ft deep in some streets. People trapped in their homes are "
                              "appealing for help on Facebook Live.", depth_ft=6),
             R(640, "severe", "Myo Ma, Kyauk Myaung and Pan Taw wards flooded; households moving out."),
             R(524, "severe", "Military government figures: five town wards flooded 6–8 ft and more than "
                              "18,000 people affected.", depth_ft=8, affected=18000),
             R(480, "severe", "Still flooded on 28 Sep, along with the villages on the Union highway."),
         ]),
    dict(id="shin-moke-tee", mm="ရှင်မုတ္ထီး", en="Shin Moke Tee", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", mimu_mm="ရှင်မုတ္တီး", match="variant",
         match_note="MIMU spells it ရှင်မုတ္တီး. The 27 Sep road post places it in Dawei Township, as MIMU does; "
                    "other posts list it with Thayetchaung.",
         reports=[
             R(638, "affected", "Named among flooded villages on the Union highway."),
             R(599, "affected", "Flooding on the road stretch."),
             R(480, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="yaung-maw", mm="ရောင်းမော်", en="Yaung Maw", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", reports=[
             R(638, "affected", "Named among flooded villages east of the Union highway."),
             R(599, "affected", "Flooding on the road stretch."),
             R(481, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="nyaung-zin", mm="ညောင်ဇင်", en="Nyaung Zin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(638, "affected", "Named among flooded villages."),
             R(480, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyar-inn", mm="ကြာအင်း", en="Kyar Inn", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(693, "affected", "Hill-stream water has flooded the paddy fields and entered houses."),
             R(481, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyet-sar-pyin", mm="ကြက်စားပြင်", en="Kyet Sar Pyin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(599, "affected", "Flooding on the Dawei–Myeik road stretch.")]),
    dict(id="kin-shey", mm="ကင်းရှေ့", en="Kin Shey", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(636, "severe", "Water came into houses from about midnight; by dawn on 27 Sep the whole ground "
                              "floor was under water, over a person's height. Families moved children to houses "
                              "in town.", depth_ft=6),
             R(481, "severe", "Still flooded on 28 Sep."),
         ]),
    dict(id="moe-shwe-kone", mm="မိုးရွှေကုန်း", en="Moe Shwe Kone", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="probable", ward="Maw Shi Kone Ward",
         match_note="Not in MIMU village points. Taken as Maw Shi Kone Ward (မော်ရှီကုန်း) of Thayetchaung "
                    "town, the closest MIMU name; shown at the ward centre.",
         reports=[
             R(639, "affected", "Houses near the stream are moving out."),
             R(481, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="saw-hpyar", mm="စော်ဖျား", en="Saw Hpyar", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(639, "affected", "Water reached houses that had never flooded; people are moving little by "
                                "little to safer places."),
             R(481, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyauk-hlay-kar", mm="ကျောက်လှေကား", en="Kyauk Hlay Kar", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(516, "affected", "Named among flooded villages east of the Union highway."),
             R(481, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="yan-taung", mm="ရန်တောင်", en="Yan Taung", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(638, "affected", "Named among flooded villages."),
                                  R(480, "affected", "Still flooded on 28 Sep.")]),
    dict(id="thin-kyun", mm="သင်းကျွန်း", en="Thin Kyun", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(596, "affected", "Vehicles from Dawei turned back here on 27 Sep; 2–4 ft of water on the road, "
                                "falling about 2 ft by 3:30 pm.", depth_ft=4, roles=["access"]),
             R(480, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="tha-yet-hnit-khwa", mm="သရက်နှစ်ခွ", en="Tha Yet Hnit Khwa", ts="Thayetchaung",
         area="Thayetchaung", hazard="flood", reports=[
             R(693, "affected", "Paddy fields flooded and water inside houses."),
             R(596, "affected", "Flooding reported by drivers."),
             R(480, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="oke-tu", mm="ဥတ္တူ", en="Oke Tu", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(693, "affected", "Paddy fields flooded and water inside houses."),
                  R(481, "affected", "Still flooded on 28 Sep.")]),
    dict(id="ti-tut-pyin", mm="တီတွတ်ပြင်", en="Ti Tut Pyin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(695, "affected", "Paddy fields flooded and water inside houses."),
                                  R(480, "affected", "Still flooded on 28 Sep (west of the road).")]),
    dict(id="pe-det", mm="ပဲဒက်", en="Pe Det", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(635, "affected", "Villages flooded all the way from past the Pauk Taing bridge checkpoint to "
                                "beyond Pe Det."),
             R(595, "affected", "Vehicles coming up from Myeik stranded near Pe Det on 27 Sep.", roles=["access"]),
             R(480, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="htee-hpa-doe", mm="ထီးဖဒို", en="Htee Hpa Doe", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="unlocated",
         match_note="No village of this name, or a close spelling, in MIMU for the region.",
         reports=[R(526, "affected", "Photo of the flooded village sent in by residents."),
                  R(481, "affected", "Still flooded on 28 Sep.")]),
    dict(id="ka-nyin-chaung", mm="ကညင်ချောင်း", en="Ka Nyin Chaung", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(482, "severe", "The bridge at Ka Nyin Chaung on Union Road No. 8 was destroyed, cutting the "
                             "Dawei–Myeik road.", roles=["access"]),
         ]),
    dict(id="taung-pyauk", mm="တောင်ပျောက်", en="Taung Pyauk area", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="approx", approx_vt="Kayin Taung Pyauk",
         match_note="The posts name the Taung Pyauk area (about 10 villages) without listing them. Shown at "
                    "the centre of Kayin Taung Pyauk village tract.",
         reports=[
             R(518, "affected", "Heavy rain since 24 Sep; flooding from the morning of 27 Sep. About 10 "
                                "villages, where the military restricts the transport of food and medicine. "
                                "Phone lines down; buffalo and cattle lost, people safe.",
               roles=["comms"], villages=10),
             R(483, "severe", "Rope bridges destroyed and flooding severe. Most villages have no phone or "
                             "internet, so details are unknown.", roles=["access", "comms"]),
         ]),

    # ================================================== Dawei town
    dict(id="dawei-town", mm="ထားဝယ်မြို့", en="Dawei town", ts="Dawei", town="Dawei", area="Dawei town",
         hazard="flood", reports=[
             R(686, "severe", "Drains overflowed and main roads went under water in some wards. Elderly people "
                              "and children trapped at home were brought out by welfare groups. Flooding in the "
                              "Mae Di Land private hospital compound on Ka Myaw Kin road; strong winds brought "
                              "down large trees.", roles=["access"]),
             R(502, "severe", "Water entered wards from the morning of 27 Sep; by evening most wards and "
                              "several streams were flooded. The Zeyawaddy monastic school near the Shwe Taung "
                              "Zar pagoda and the Ghositarama Pali University (Taik Thit) are flooded. Power was "
                              "cut to the town and surrounding villages, and some schools closed."),
             R(607, "severe", "Most wards still flooded."),
             R(494, "severe", "Still raining and windy on the morning of 28 Sep; no electricity."),
         ]),
    dict(id="kyauk-maw-ward", mm="ကျောက်မော်ရပ်ကွက်", en="Kyauk Maw ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ကျောက်မော်ရပ်ကွက်", reports=[
             R(503, "affected", "A resident: water is everywhere, even where it has never come before."),
         ]),
    dict(id="bon-maw-ward", mm="ဘုမ္မော်ရပ်ကွက်", en="Bon Maw ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ဘုမ္မော်ရပ်ကွက်", reports=[
             R(489, "severe", "Single-storey houses under water on the morning of 28 Sep. The football ground "
                              "and walls of Basic Education High School No. 2 are submerged, and single-storey "
                              "houses on Mya Sabai street are flooded.", roles=["school"]),
         ]),
    dict(id="ka-nyon-ward", mm="ကညုံရပ်ကွက်", en="Ka Nyon ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ကညုံရပ်ကွက်", reports=[
             R(505, "severe", "Near the Taik Thit monastery, 10 people including elderly people and a child "
                              "were rescued on the evening of 27 Sep by the regional emergency team and the "
                              "Red Cross.", rescued=10),
             R(491, "severe", "Water in compounds on Taik Thit Kyaung road; some single-storey houses "
                              "submerged. A resident of more than ten years has never seen flooding like it."),
         ]),
    dict(id="kyet-sa-pyin-ward", mm="ကြက်စားပြင်ရပ်ကွက်", en="Kyet Sa Pyin ward", ts="Dawei",
         area="Dawei town", hazard="flood", ward_mm="ကြက်စားပြင်ရပ်ကွက်", reports=[
             R(489, "severe", "Some single-storey houses under water on the morning of 28 Sep."),
         ]),
    dict(id="ka-yat-pyin-ward", mm="ကရပ်ပြင်ရပ်ကွက်", en="Ka Yat Pyin ward", ts="Dawei", area="Dawei town",
         hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards (the boundaries predate newer wards).",
         reports=[R(489, "severe", "Single-storey houses under water; side streets of Ka Yat Pyin (North) "
                                   "flooded.")]),
    dict(id="shan-ma-le-swe-ward", mm="ရှမ္မလည်ဆွဲရပ်ကွက်", en="Shan Ma Le Swe ward", ts="Dawei",
         area="Dawei town", hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards.",
         reports=[R(489, "severe", "Single-storey houses under water; side streets flooded.")]),
    dict(id="khon-win-dat-ward", mm="ခုံဝင်းဒပ်ရပ်ကွက်", en="Khon Win Dat ward", ts="Dawei", area="Dawei town",
         hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards. The post places it behind the regional military "
                    "government office.",
         reports=[R(493, "affected", "Knee-deep water since 27 Sep on the road east of the Shwe Hlyit Hmyaung "
                                     "pagoda.")]),
    dict(id="pauk-taing", mm="ပေါက်တိုင်း", en="Pauk Taing bridge", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", bridge="Pauk Taing Bridge", reports=[
             R(635, "affected", "The checkpoint at Pauk Taing bridge, at the entrance to Dawei, marks the "
                                "northern end of the flooded stretch that runs south past Pe Det.",
               roles=["access"]),
         ]),

    # ================================================== Dawei, east (road to Htee Khee)
    dict(id="za-lun", mm="ဇလွန်း", en="Za Lun", ts="Dawei", area="Dawei east", hazard="flood",
         reports=[R(691, "affected", "Flooded; water over the Dawei–Htee Khee road in the forest east of "
                                     "Dawei.", roles=["access"])]),
    dict(id="ta-laing-taung", mm="တလိုင်းတောင်", en="Ta Laing Taung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[R(691, "affected", "Flooded; water over the Dawei–Htee Khee road.",
                                    roles=["access"])]),
    dict(id="pa-kar-ri", mm="ပကာရီ", en="Pa Kar Ri", ts="Dawei", area="Dawei east", hazard="flood",
         reports=[
             R(691, "affected", "Flooded, according to residents' photos and video."),
             R(428, "severe", "Water entered on the morning of 27 Sep and rose fast. By night houses on higher "
                             "ground were flooded to the first floor and low-lying houses were completely "
                             "submerged. The whole village is under water and the border road is impassable.",
               depth_ft=10, roles=["access"]),
         ]),
    dict(id="san-chi", mm="ဆန်းချီ", en="San Chi", ts="Dawei", area="Dawei east", hazard="flood",
         vt_hint="Pa Kar Ri", reports=[
             R(581, "affected", "Water flowing over the San Chi bridge.", roles=["access"]),
             R(433, "severe", "Video shows the San Chi village bridge submerged.", roles=["access"]),
         ]),
    dict(id="yam-ma-zu", mm="ရမ္မဇူ", en="Yam Ma Zu", ts="Dawei", area="Dawei east", hazard="both",
         reports=[R(434, "affected", "Flooded. A landslide inside the Yam Ma Zu private school compound has "
                                    "closed the school.", roles=["school"])]),
    dict(id="leik-kyei-pyaung", mm="လိပ်ကြယ်ပြောင်", en="Leik Kyei Pyaung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[R(434, "affected", "Flooded.")]),
    dict(id="thin-gan-tone", mm="သင်္ကန်းတုံး", en="Thin Gan Tone", ts="Dawei", area="Dawei east",
         hazard="flood", match="unlocated",
         match_note="Not in MIMU village points; the post places it in Pa Kar Ri village tract.",
         reports=[R(434, "affected", "Flooded.")]),
    dict(id="tha-yet-ngoke", mm="သရက်ငုတ်", en="Tha Yet Ngoke", ts="Dawei", area="Dawei east",
         hazard="landslide", reports=[
             R(435, "affected", "A landslide on the main road nearby leaves room for only one vehicle at a "
                               "time.", roles=["access"]),
         ]),

    # ================================================== Yebyu
    dict(id="kaleinaung", mm="ကလိန်အောင်", en="Kaleinaung", ts="Yebyu", town="Kaleinaung", area="Yebyu",
         hazard="flood", reports=[
             R(697, "affected", "Water over the road in places on the Union highway and at Kaleinaung, but "
                                "traffic can still pass.", roles=["access"]),
             R(585, "affected", "Nothing else unusual in Yebyu Township, residents say."),
         ]),

    # ================================================== Palaw (Myeik District)
    dict(id="palauk", mm="ပလောက်", en="Palauk", ts="Palaw", town="Palauk", area="Palaw", hazard="flood",
         reports=[
             R(707, "affected", "Flooding: water in houses and over the main road, residents' records show."),
             R(595, "affected", "Some vehicles stranded beyond Palauk, at the foot of Bok Taung.",
               roles=["access"]),
         ]),
    dict(id="pa-wut-kone", mm="ပဝတ်ကုန်း", en="Pa Wut Kone", ts="Palaw", area="Palaw", hazard="flood",
         reports=[R(600, "affected", "Flooding over broken stretches of the road between Palaw and Pala.",
                    roles=["access"])]),
    dict(id="ka-de", mm="ကဒဲ", en="Ka De", ts="Palaw", area="Palaw", hazard="flood",
         reports=[R(600, "affected", "Flooding over broken stretches of the road between Palaw and Pala.",
                    roles=["access"])]),

    # ================================================== Tanintharyi (Myeik District)
    dict(id="tanintharyi-town", mm="တနင်္သာရီမြို့", en="Tanintharyi town", ts="Tanintharyi",
         town="Tanintharyi", area="Tanintharyi", hazard="flood", reports=[
             R(705, "affected", "The Tanintharyi River, which rises in Dawei District, has been rising since "
                                "26 Sep and on 27 Sep was about 2 ft below its 17 ft alert mark. Low-lying "
                                "wards of the town are flooded.", river_ft=15),
             R(413, "affected", "Phone and internet lines cut from the evening of 27 Sep.", roles=["comms"]),
         ]),
    dict(id="tha-kyet", mm="သကျက်", en="Tha Kyet", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[R(408, "affected", "Stream water came in on the night of 27 Sep; roads knee-deep and some "
                                    "places impassable.", depth_ft=2)]),
    dict(id="ta-ku", mm="တကူ", en="Ta Ku", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         vt_hint="Ta Ku", reports=[R(411, "affected", "The Tanintharyi River began rising on 27 Sep and is rising "
                                                     "fast; the paddy fields are full of water.")]),
    dict(id="thar-ra-bwin", mm="သာရဘွင်", en="Thar Ra Bwin", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[
             R(410, "affected", "The bridge linking Thar Ra Bwin with Ashay Kan (the east-bank village) is under "
                               "water, and water is entering some roads.", roles=["access"]),
         ]),
]

# ---------------------------------------------------------------------------
# 29 Sep update. What the later 28 Sep posts and the 29 Sep posts add about the
# places above (appended to their reports; main() re-sorts them by day and post),
# then the places they name for the first time.
# ---------------------------------------------------------------------------
LIST28 = "Named among the Launglon villages hit by floods and landslides in the 28 Sep explainer."
RECEDED_28 = "Among the worst-flooded places; the water fell on the evening of 28 Sep."
TNI_TRACTS = ("Among 20-odd villages in nine tracts along the Tanintharyi River and its streams under water after "
              "three days of rain.")

MORE = {
    # ---------------------------------------------- Launglon
    "ka-myaw-gyi": [R(372, "affected", RECEDED_28, roles=["receding"])],
    "way-di": [
        R(372, "affected", RECEDED_28, roles=["receding"]),
        R(374, "affected", "By the Dawei River. From about 9 pm on 26 Sep the water rose to nearly 5 ft on the road "
                           "between Kone Zayat and Way Di, cutting the village off; most residents moved to the "
                           "monastery. About 20 cattle were swept away; seven were saved as the water fell on "
                           "28 Sep. No one was hurt.", depth_ft=5, roles=["access", "relief", "receding"]),
    ],
    "min-yat": [
        R(197, "fatal", "One body recovered.", dead=1),
        R(372, "fatal", RECEDED_28, roles=["receding"]),
        R(64, "fatal", "One body recovered (29 Sep round-up).", dead=1),
    ],
    "tha-byar": [
        R(161, "severe", "On 27 Sep rescuers had to borrow two tractors to clear the road near Tha Byar; a backhoe "
                         "went down on the morning of 28 Sep.", roles=["access"]),
        R(372, "severe", RECEDED_28, roles=["receding"]),
        R(118, "fatal", "A mother and son, the wife and son of Ko Aung Shein (Ko Aung Thar) of Kayin Gyi, have been "
                        "missing since the slide of 26 Sep and were still not found on the morning of 29 Sep.",
          missing=2),
        R(121, "fatal", "At least four houses almost completely destroyed and nearly 200 filled with silt; rubber, "
                        "betel-nut and cashew orchards buried. Residents say this slide is bigger than 1997's.",
          houses=4),
        R(64, "fatal", "A mother and son missing (29 Sep round-up).", missing=2),
        R(3, "fatal", "Still not found four days on.", missing=2),
    ],
    "thea-pon": [
        R(85, "severe", "A slide on Inwa hill on the night of 26 Sep brought down monastery buildings at the foot "
                        "of the hill and buried orchards near the village; no one was hurt. Damage to outlying "
                        "orchards is unknown, and the road up the hill has collapsed.", roles=["access"]),
    ],
    "launglon-town": [R(372, "affected", "The water fell on the evening of 28 Sep.", roles=["receding"])],
    "nyin-maw": [
        R(159, "affected", "The rescue teams' base: relief supplies are collected here and handed out.",
          rescue="reached", roles=["relief"]),
        R(30, "affected", "Backhoes have cleared the road as far as Nyin Maw.", rescue="reached"),
        R(13, "affected", "The slide debris on the hill road between Nyin Maw and Ti Zit still has to be cleared.",
          roles=["access"]),
    ],
    "ka-det-nge-htein": [
        R(163, "fatal", "A rescue volunteer names it the worst hit, with the most deaths."),
        R(270, "fatal", "31 houses completely destroyed; the buried ground covers about five football pitches, "
                        "starting beside the Kadet Nge hill monastery.", houses=31),
        R(262, "fatal", "Three more bodies found on 28 Sep, five in all; 13 people went missing in the slide on "
                        "the night of 26 Sep. The Zambu Thiri team recovered 12-year-old Maung Ar Kar Min and a "
                        "monk in the afternoon; residents found the other three. The search resumes with "
                        "residents on 29 Sep.", dead=5),
        R(197, "fatal", "Five bodies recovered; dozens missing.", dead=5, missing_text="dozens"),
        R(187, "fatal", "Red level: bodies found and dozens still missing.", red=True),
        R(381, "fatal", "Emergency search and rescue under way since the morning of 28 Sep.", rescue="reached"),
        R(124, "fatal", "Red level; the search for the missing continues on 29 Sep.", red=True),
        R(62, "fatal", "Ten bodies recovered and three still missing. An advance team of a dozen or so has been "
                       "working here since 28 Sep.", dead=10, missing=3, rescue="reached"),
    ],
    "ka-det-gyi": [
        R(286, "fatal", "The bodies of a mother and son, Daw Khin Aye, over 70, and U Myo Thein, about 45, a deputy "
                        "village administrator, were found under slide earth in their rubber and durian orchard a "
                        "few miles from the village on the evening of 28 Sep. They were cremated the same day.",
          dead=2),
        R(205, "fatal", "A slide filled an orchard; a mother and son died.", dead=2),
        R(63, "fatal", "Two bodies recovered (29 Sep round-up).", dead=2),
    ],
    "taw-kye": [R(208, "affected", "Slides; residents have had no help.", roles=["needs"])],
    "tha-kyet-taw": [R(215, "affected", "No emergency rescue team had arrived by the evening of 28 Sep.",
                       rescue="not-reached")],
    "ra-be": [R(215, "affected", "No emergency rescue team had arrived by the evening of 28 Sep.",
                rescue="not-reached")],
    "za-lut": [
        R(215, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(34, "fatal", "Damage reported here too, north of Kyauk Ni Maw."),
    ],
    "za-lut-pyin-gyi": [
        R(214, "fatal", LIST28),
        R(34, "fatal", "Damage reported (as Pyin Gyi, north of Kyauk Ni Maw)."),
    ],
    "kyauk-ni-maw": [
        R(127, "fatal", "About 50 houses buried since the evening of 26 Sep and at least five people missing. The "
                        "worst slide hit the crowded junction of the lower road (In Ni Twin) and the upper road (by "
                        "the school). No search has been possible; more than 200 residents are in the monastery "
                        "and urgently need food and medicine.",
          houses=50, missing=5, sheltering=200, rescue="not-reached", roles=["relief", "needs"]),
        R(197, "fatal", "Two bodies recovered.", dead=2),
        R(215, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(105, "fatal", "Word reaching Nyaw Pyin: about 50 houses collapsed; eight people buried, two dead and six "
                        "missing (unconfirmed).", dead=2, missing=6),
        R(64, "fatal", "The 29 Sep round-up lists eight residents missing and no bodies recovered.",
          dead=0, missing=8),
        R(21, "fatal", "More than 50 houses damaged and at least five people missing. Burned by the junta in late "
                       "2024, the village had been rebuilding for barely a year.", houses=50, missing=5),
        R(26, "fatal", "More than 200 villagers at the monastery, which feeds them from its own rice. About five "
                       "dead or missing, one from this house, one from that. No rescue team has got in; those left "
                       "dig by hand, with no backhoe.", sheltering=200, rescue="not-reached",
          roles=["relief", "needs"]),
        R(30, "fatal", "Neighbourhoods are cut off from each other by debris. Nearly every village on the road from "
                       "Dawei has slides, so rescuers may take days to get here.", roles=["access"]),
        R(34, "fatal", "Many bridges destroyed on the way down to Shin Maw.", roles=["access"]),
    ],
    "nyaw-pyin": [
        R(133, "fatal", "Hills collapsed here too."),
        R(197, "fatal", "Two bodies recovered.", dead=2),
        R(215, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(95, "fatal", "A fishing village near Grandfather Beach, 30-odd miles south of Launglon, burned by the junta "
                       "again and again since the coup. The slide and strong winds of 26 Sep destroyed more than 30 "
                       "houses; two residents were killed.", dead=2, houses=30),
        R(101, "fatal", "At least two slides round the village, and more towards Grandfather Beach; the one beside "
                        "the road killed the two."),
        R(103, "fatal", "The roads between villages are blocked, so aid cannot get in. A fishing village with no "
                        "work in the monsoon and no money to rebuild.", roles=["needs", "access"]),
        R(64, "fatal", "Two bodies recovered (29 Sep round-up).", dead=2),
    ],
    "ti-zit": [
        R(11, "fatal", "A beach village about four miles south-west of Launglon, over the hill from Nyin Maw. Slides "
                       "from the surrounding hills on the night of 26 Sep buried its streets and the hill road, "
                       "cutting it off.", roles=["access"], rescue="not-reached"),
        R(12, "fatal", "No cars or motorcycles can get out, and on foot people sink in the mud; villagers had to "
                       "carry home on a stretcher a body brought back from hospital."),
        R(14, "fatal", "The phone tower runs on fuel that will soon run out; people are living on what the village "
                       "shops had in stock.", roles=["comms", "needs"]),
        R(15, "fatal", "Eight houses destroyed and nearly 40 buried, with many orchards.", houses=40),
        R(16, "fatal", "Nearly 600 households, more than 1,000 people, need emergency food.", roles=["needs"]),
    ],
    "kayin-gyi": [
        R(157, "severe", "Hills also collapsed on the Kayin Gyi and Kan Pa Ni side, where teams from Maungmagan are "
                         "working."),
        R(218, "severe", "About 100 junta troops entered Kyauk Sin village tract, which includes Kayin Gyi, saying "
                         "they had come to help; residents fled, and the troops stayed at Kyauk Sin."),
    ],
    "maungmagan": [
        R(157, "affected", "Hills have collapsed on this side too; the Maungmagan rescue teams are working here."),
    ],
    # ---------------------------------------------- Dawei
    "dawei-town": [
        R(358, "severe", "Rain stopped from midday on 28 Sep and the water began to fall; rain returned in the "
                         "evening.", roles=["receding"]),
        R(282, "severe", "Electricity off since about 4 pm on 27 Sep and some phone lines down, still on the evening "
                         "of 28 Sep.", roles=["comms"]),
        R(274, "severe", "More than 600 flood victims, moved out overnight on 27 Sep, are sheltering at Pahtoe "
                         "Kyaung, Mattaya Kyaung, Zambu Htein Lin Kyaung, the Moe Kaung meditation centre and Dhamma "
                         "Sekya Kyaung and need food, clothes and medicine; the Red Cross is giving health care. "
                         "Wards still flooded on the evening of 28 Sep.", sheltering=600, roles=["relief", "needs"]),
        R(173, "severe", "Knee-deep water inside houses at the bend of Post Office Road on 28 Sep; a resident of "
                         "about 80 has never seen the like."),
        R(110, "severe", "Water falling in the town wards on the morning of 29 Sep. The sun is out and most "
                         "evacuees have gone home to clean up. Power still off at midday.", roles=["receding"]),
    ],
    "bon-maw-ward": [
        R(279, "severe", "Residents still at home on streets 2, 4, 5 and 6 need drinking water and food parcels.",
          roles=["needs"]),
        R(175, "severe", "Every street under water on 28 Sep."),
        R(115, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "ka-nyon-ward": [
        R(276, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(115, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "kyet-sa-pyin-ward": [
        R(276, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(279, "severe", "People still at home need food parcels.", roles=["needs"]),
        R(111, "severe", "Houses under water from the night of 27 Sep; water falling in town wards on 29 Sep.",
          roles=["receding"]),
    ],
    "ka-yat-pyin-ward": [R(276, "severe", "Residents of Ka Yat Pyin South and North moved out overnight on 27 Sep.",
                           roles=["relief"])],
    "shan-ma-le-swe-ward": [R(276, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"])],
    "khon-win-dat-ward": [
        R(276, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(115, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "za-lun": [R(283, "affected", "Cars and motorcycles could not get through on the road between Byaw Taw Wa and "
                                  "Za Lun on the evening of 28 Sep.", roles=["access"])],
    "pa-kar-ri": [R(227, "severe", "Villages in the tract are flooded and cut off from each other; residents in "
                                   "monasteries need food.", roles=["relief", "needs"])],
    # ---------------------------------------------- Thayetchaung
    "thayetchaung-town": [
        R(318, "severe", "The whole market flooded: rice, oil, eggs and other food lost. Wells are under water, so "
                         "drinking water is scarce.", roles=["needs"]),
        R(346, "severe", "The local Myat Parami charity can move only town-ward residents to safety; it has no boats "
                         "to reach the villages, and the district's teams are in Launglon.", roles=["needs"]),
        R(138, "fatal", "A man of about 60 with a mental illness was swept away and died, and a 90-year-old woman "
                        "died of exhaustion as she moved within her flooded house.", dead=2),
        R(37, "fatal", "The water has fallen, but the power is off, so phone lines are still down. Flooding ran "
                       "2–8 ft from midnight on 26 Sep to the morning of 28 Sep: it dipped on the evening of 27 Sep, "
                       "rose again on the morning of 28 Sep and fell from that afternoon, when the clean-up of mud "
                       "and fallen trees began.", roles=["receding", "comms"]),
        R(43, "fatal", "Flooded villages need drinking water, food and clothes, and help clearing the silt.",
          roles=["needs"]),
        R(67, "fatal", "Two dead in the town (29 Sep round-up).", dead=2),
    ],
    "saw-hpyar": [
        R(320, "fatal", "One resident killed by trees brought down by strong winds on the night of 27 Sep.", dead=1),
        R(332, "fatal", "Water starting to fall on 28 Sep, but still impassable while the rain goes on.",
          roles=["receding"]),
        R(137, "fatal", "A couple in their 50s killed by a falling tree.", dead=2),
        R(67, "fatal", "Two dead (29 Sep round-up).", dead=2),
    ],
    "kin-shey": [R(332, "severe", "Water starting to fall on 28 Sep, but still impassable while the rain goes on.",
                   roles=["receding"])],
    "ka-nyin-chaung": [
        R(137, "fatal", "A couple drowned.", dead=2),
        R(67, "fatal", "Two dead (29 Sep round-up).", dead=2),
    ],
    "kyar-inn": [
        R(329, "severe", "Water over a person's height on the road to Nyaung Zin and phone lines cut since 27 Sep. A "
                         "resident: the whole village is trapped inside; no one can get out.",
          depth_ft=6, roles=["access", "comms"]),
    ],
    "kyet-sar-pyin": [
        R(38, "affected", "A resident: the water has fallen and she has heard from home, but with the power out the "
                          "phones still don't work.", roles=["receding", "comms"]),
    ],
    "kyauk-hlay-kar": [R(141, "affected", "A house destroyed by a falling tree.")],
    "taung-pyauk": [
        R(336, "severe", "Phones and internet cut since the morning of 27 Sep. The area is held by resistance forces "
                         "and has long been under junta blockade.", roles=["comms"]),
        R(143, "severe", "Water still not falling on the evening of 28 Sep; rescue teams cannot move people trapped "
                         "in some villages.", roles=["needs"]),
    ],
    "pe-det": [R(347, "affected", "Residents asked for help, but water over the highway stopped the Myat Parami team "
                                  "getting there.", roles=["needs"])],
    # ---------------------------------------------- Tanintharyi
    "tanintharyi-town": [
        R(53, "affected", "Some low-lying residents have moved to higher ground for now.", roles=["relief"]),
        R(49, "affected", "At about 3 pm on 29 Sep the river stood above 26 ft, more than 2 ft over its 24 ft danger "
                          "mark. Rain stopped the day before, but water coming down from the Dawei side keeps it "
                          "rising. With the town's gates shut and water pumped out, the town itself is drier than "
                          "in August.", river_ft=26),
    ],
    "tha-kyet": [
        R(74, "affected", TNI_TRACTS),
        R(77, "severe", "Low-lying houses under water in some villages of the tract and residents moving to higher "
                        "ground: knee-deep the day before, waist-deep on 29 Sep and a person's height in low spots.",
          depth_ft=6),
    ],
    "ta-ku": [
        R(74, "affected", TNI_TRACTS),
        R(75, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so people "
                          "travel by boat and raft.", roles=["access"]),
    ],
    "thar-ra-bwin": [
        R(74, "affected", TNI_TRACTS),
        R(75, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so people "
                          "travel by boat and raft.", roles=["access"]),
    ],
}
_BY = {s["id"]: s for s in SITES}
for _k, _rs in MORE.items():
    _BY[_k]["reports"].extend(_rs)

TNI_LOW = ("Low-lying houses under water in some villages of the tract and residents moving to higher ground: "
           "knee-deep the day before, waist-deep on 29 Sep and a person's height in low spots.")
SITES += [
    # ================================================== Launglon
    dict(id="tha-win", mm="သဝင်", en="Tha Win", ts="Launglon", area="Launglon south", hazard="both",
         reports=[R(214, "affected", LIST28)]),
    dict(id="auk-kyauk-wut", mm="အောက်ကျောက်ဝပ်", en="Auk Kyauk Wut", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(133, "affected", "Hills collapsed here too."),
             R(105, "affected", "Hills beside the village collapsed, but no houses in the village fell."),
         ]),
    dict(id="kyauk-wut-pyin", mm="ကျောက်ဝပ်ပြင်", en="Kyauk Wut Pyin", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(34, "affected", "The whole road on from Kyauk Ni Maw through Kyauk Wut Pyin is in difficulty, and many "
                               "places still cannot be reached.", roles=["access"]),
         ]),
    dict(id="pa-nyit", mm="ပညစ်", en="Pa Nyit", ts="Launglon", area="Launglon north-west", hazard="landslide",
         reports=[
             R(364, "severe", "Slides in the village and on the road after the heavy rain of 27 Sep; residents are "
                              "moving to safety."),
             R(365, "severe", "Two houses buried, no one hurt. Road slides have cut off parts of the area.",
               houses=2, roles=["access", "comms"]),
             R(212, "severe", "Two houses buried on 27 Sep; no one was killed, but residents are moving to safety.",
               houses=2),
             R(214, "severe", LIST28),
         ]),
    dict(id="kan-pa-ni", mm="ကမ်းပနီ", en="Kan Pa Ni", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(366, "affected", "A slide blocks the road between Pa Nyit and Kan Pa Ni.", roles=["access"]),
             R(157, "affected", "Hills collapsed on the Kayin Gyi and Kan Pa Ni side; teams from Maungmagan are "
                                "working there."),
         ]),
    dict(id="shan-maw", mm="ရှမ်းမော်", en="Shan Maw", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(367, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),
    dict(id="kyone-ga-nan", mm="ကျုံဂဏန်း", en="Kyone Ga Nan", ts="Launglon", area="Launglon north-west",
         hazard="landslide", mimu_mm="ကျုံးဂဏန်း", match="variant",
         match_note="MIMU spells it ကျုံးဂဏန်း, in San Hlan village tract, 3 km south of Shan Maw.",
         reports=[
             R(367, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),
    dict(id="pein-ne-chaung", mm="ပိန္နဲချောင်း", en="Pein Ne Chaung", ts="Launglon", area="Launglon north-west",
         hazard="landslide", match="unlocated",
         match_note="MIMU's only Pein Hne Chaung is in Dawei Township, 25 km away across the river, not a village "
                    "reached through Pa Nyit.",
         reports=[
             R(367, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),

    # ================================================== Dawei
    dict(id="pyar-thar-chaung", mm="ပျားသားချောင်း", en="Pyar Thar Chaung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[
             R(70, "fatal", "Two children killed by a tree that fell as the flood ran strong.", dead=2),
         ]),

    # ================================================== Thayetchaung
    dict(id="kyauk-aing", mm="ကျောက်အိုင်", en="Kyauk Aing", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(140, "fatal", "A father and son swept away by the current; missing.", missing=2),
             R(68, "fatal", "Still missing on 29 Sep.", missing=2),
         ]),
    dict(id="mei-ke", mm="မယ်ကဲ", en="Mei Ke", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(141, "affected", "Two rope bridges destroyed.", roles=["access"])]),
    dict(id="ah-lel-su", mm="အလယ်စု", en="Ah Lel Su", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(44, "affected", "In the Taung Pyauk area. The water has fallen and the rain has stopped, a "
                                    "resident says.", roles=["receding"])]),
    *[dict(id=i, mm=mm, en=en, ts="Thayetchaung", area="Thayetchaung", hazard="flood", **kw,
           reports=[R(323, "affected", "Flooded near Thayetchaung town; phone lines are down, so there are no "
                                       "details.", roles=["comms"])])
      for i, mm, en, kw in [
          ("sin-ku", "ဆင်ကူး", "Sin Ku", {}),
          ("ya-nge", "ရငဲ", "Ya Nge", dict(mimu_mm="ရေငဲ (ရငဲ)", match="variant",
                                            match_note="MIMU lists it as ရေငဲ (ရငဲ), Yae Nge (Ya Nge).")),
          ("pi-taing", "ပိတိုင်", "Pi Taing", {}),
          ("min-dat", "မင်းဒပ်", "Min Dat", {}),
          ("son-sin-hpyar", "စုံစင်ဖျား", "Son Sin Hpyar", {}),
          ("pyin-hpyu-gyi", "ပြင်းဖြူကြီး", "Pyin Hpyu Gyi", {}),
      ]],

    # ================================================== Tanintharyi
    dict(id="thein-daw", mm="သိန္ဓော", en="Thein Daw tract", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt="Thein Daw",
         match_note="A village tract (MIMU: သိန်းဒေါ Thein Daw); shown at the tract's centre.",
         reports=[
             R(74, "affected", TNI_TRACTS),
             R(75, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so "
                               "people travel by boat and raft.", roles=["access"]),
         ]),
    dict(id="ban-law", mm="ဘန်းလော", en="Ban Law", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         mimu_mm="ဘန်လော", vt_hint="Ban Law", match="variant",
         match_note="Named as a village tract; shown at MIMU's Ban Law village (ဘန်လော).",
         reports=[R(74, "affected", TNI_TRACTS)]),
    dict(id="maw-tone", mm="မော်တုန်း", en="Maw Tone tracts", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt=["Maw Tone (East)", "Maw Tone (West)"],
         match_note="MIMU splits Maw Tone (မော်တုံး) into East and West village tracts; shown at the centre of the "
                    "two.",
         reports=[R(74, "affected", TNI_TRACTS), R(77, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="pa-wa", mm="ပဝ", en="Pa Wa tract", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         match="approx", approx_vt="Pa Wa",
         match_note="A village tract with no village of that name in MIMU; shown at the tract's centre.",
         reports=[R(74, "affected", TNI_TRACTS), R(77, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="chaung-la-mu", mm="ချောင်းလမု", en="Chaung La Mu", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[R(74, "affected", TNI_TRACTS), R(77, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="aw-gyi", mm="အော်ကြီး", en="Aw Gyi", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[R(54, "affected", "Travellers say the rising river is over the Myeik–Tanintharyi road here.",
                    roles=["access"])]),
    dict(id="u-yin-kwin", mm="ဥယျာဉ်ကွင်း", en="U Yin Kwin", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", mimu_mm="ဥယျာဉ်ကမ်း", match="probable",
         match_note="Taken as MIMU's U Yin Kan (ဥယျာဉ်ကမ်း), 3 km from Aw Gyi in the same tract; no U Yin Kwin in "
                    "MIMU.",
         reports=[R(54, "affected", "Travellers say the rising river is over the Myeik–Tanintharyi road here.",
                    roles=["access"])]),
    dict(id="lel-taung-yar", mm="လယ်တောင်ယာ", en="Lel Taung Yar", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[
             R(55, "affected", "About 5 ft of water on the Tanintharyi–Kawthoung road: vehicles cannot pass, and "
                               "motorcycles are ferried across on rafts.", depth_ft=5, roles=["access"]),
         ]),

    # ================================================== Bokpyin (Kawthoung District)
    dict(id="lay-hnya", mm="လေညှာ", en="Lay Hnya", ts="Bokpyin", area="Bokpyin", hazard="flood",
         mimu_mm="လေညာ", match="variant",
         match_note="MIMU spells it လေညာ (Lay Nyar), as the post itself does once; Htaung Yaik village tract.",
         reports=[
             R(180, "affected", "The Lay Hnya river rose into the village on 27 Sep: roads and low-lying houses under "
                                "water, and residents of the low ground moving up the pagoda hill. Knee-deep in the "
                                "village centre, with rain still falling on the evening of 28 Sep.", depth_ft=2),
         ]),
]

# Places the posts use only as reference points
REFERENCES = [
    dict(id="shin-maw", mm="ရှင်မော်", en="Shin Maw", line=547,
         note="Southern end of the affected stretch of the Launglon peninsula, home to one of the 'nine "
              "Shins' pagodas. Not in MIMU village points, so not mapped."),
    dict(id="htee-khee", mm="ထီးခီး", en="Htee Khee", line=426,
         note="Thai–Myanmar border crossing at the far end of the Dawei–Htee Khee road."),
    dict(id="sez", mm="ထားဝယ် အထူးစီးပွားရေးဇုန်", en="Dawei SEZ deep-sea port", line=698,
         note="Its condition was still being checked on 27 Sep."),
]

# Incidents that are not a village. `at` = a site's position; `between` = midpoint
# of two sites, moved onto the nearest MIMU road.
INCIDENTS = [
    dict(id="poe-zar-pin", kind="road-block", en="Poe Zar Pin landslide", mm="ပိုးစာပင်တောင်ပြို",
         between=["launglon-town", "nyin-maw"], line=530, day=27,
         text="The hill between Launglon town and Nyin Maw collapsed on the morning of 27 Sep, burying the "
              "road in earth, rock and trees. It stopped the rescue convoy at about 2:30 pm; the alternative "
              "route by Pyin Htein was under water a person's height deep.",
         match_note="Hill not in MIMU. Placed midway between Launglon town and Nyin Maw, then moved onto the "
                    "nearest MIMU road."),
    dict(id="pyin-htein-route", kind="flooded-road", en="Pyin Htein route under water", mm="ပြင်းထိန်ရွာလမ်း",
         at="pyin-htein", line=532, day=27,
         text="The detour around the Poe Zar Pin slide through Pyin Htein was under water about a person's "
              "height deep."),
    dict(id="ka-myaw-gyi-road", kind="flooded-road", en="Road closed at Ka Myaw Gyi", mm="ကမြောကြီး",
         at="ka-myaw-gyi", line=675, day=27,
         text="Vehicles barred from Ka Myaw Gyi, at the Dawei–Launglon boundary, onward; flooding held up "
              "rescue teams there on the morning of 27 Sep."),
    dict(id="shin-maw-road", kind="road-cut", en="Road to Shin Maw destroyed", mm="ကျောက်နီမော်–ရှင်မော်လမ်း",
         at="kyauk-ni-maw", line=666, day=27,
         text="The road from Kyauk Ni Maw to Shin Maw is destroyed and impassable."),
    dict(id="kayin-gyi-bridge", kind="bridge-out", en="Kayin Gyi bridge and roads destroyed", mm="ကရင်ကြီး တံတား",
         at="kayin-gyi", line=417, day=28,
         text="The second slide destroyed the village bridge and roads; the road by the bridge is cut."),
    dict(id="san-chi-bridge", kind="bridge-flood", en="San Chi bridge submerged", mm="ဆန်းချီတံတား",
         at="san-chi", line=581, day=27,
         text="Water over the San Chi bridge on 27 Sep; submerged by 28 Sep."),
    dict(id="pa-kar-ri-road", kind="road-cut", en="Dawei–Htee Khee road impassable", mm="ထားဝယ်-ထီးခီးလမ်း",
         at="pa-kar-ri", line=436, day=28,
         text="With Pa Kar Ri under water, vehicles cannot pass on the Dawei–Htee Khee border road."),
    dict(id="tha-yet-ngoke-slide", kind="road-slide", en="Slide on the road near Tha Yet Ngoke", mm="သရက်ငုတ်",
         at="tha-yet-ngoke", line=435, day=28,
         text="A landslide on the main road leaves one lane; vehicles pass one at a time."),
    dict(id="ka-nyin-chaung-bridge", kind="bridge-out", en="Ka Nyin Chaung bridge destroyed",
         mm="ကညင်ချောင်း တံတား", at="ka-nyin-chaung", line=482, day=28,
         text="The bridge on Union Road No. 8 at Ka Nyin Chaung was destroyed, cutting the Dawei–Myeik road."),
    dict(id="thin-kyun-road", kind="flooded-road", en="Dawei–Myeik road flooded", mm="ထားဝယ်-မြိတ်လမ်း",
         at="thin-kyun", line=597, day=27,
         text="2–4 ft of water on the road on 27 Sep: vehicles from Dawei turned back at Thin Kyun, vehicles "
              "from Myeik were stranded near Pe Det and beyond Palauk. By 28 Sep some stretches were 6–8 ft "
              "deep."),
    dict(id="tha-ra-bwin-bridge", kind="bridge-flood", en="Thar Ra Bwin bridge submerged", mm="သာရဘွင် တံတား",
         at="thar-ra-bwin", line=410, day=28,
         text="The bridge linking Thar Ra Bwin and the east-bank village is under water."),
    # ---- 29 Sep update
    dict(id="pa-nyit-road-e", kind="road-slide", en="Slide on the road to Pa Nyit", mm="လောင်းလုံး–ပညစ်လမ်း",
         between=["launglon-town", "pa-nyit"], line=366, day=28,
         text="Photos show a slide across the road between Launglon town and Pa Nyit.",
         match_note="Placed midway between Launglon town and Pa Nyit, then moved onto the nearest MIMU road."),
    dict(id="pa-nyit-road-n", kind="road-slide", en="Slide on the road to Kan Pa Ni", mm="ပညစ်–ကမ်းပနီလမ်း",
         between=["pa-nyit", "kan-pa-ni"], line=366, day=28,
         text="A second slide between Pa Nyit and Kan Pa Ni. Shan Maw, Pein Ne Chaung and Kyone Ga Nan, reached "
              "through Pa Nyit, are cut off.",
         match_note="Placed midway between Pa Nyit and Kan Pa Ni, then moved onto the nearest MIMU road."),
    dict(id="za-lun-road", kind="flooded-road", en="Road near Za Lun impassable", mm="ဗျောတောဝ–ဇလွန်းလမ်း",
         at="za-lun", line=283, day=28,
         text="Cars and motorcycles could not get through between Byaw Taw Wa and Za Lun, east of Dawei, on the "
              "evening of 28 Sep."),
    dict(id="mei-ke-bridges", kind="bridge-out", en="Two rope bridges destroyed at Mei Ke", mm="မယ်ကဲ ကြိုးတံတား",
         at="mei-ke", line=141, day=28, text="Two rope bridges at Mei Ke, Thayetchaung, were destroyed."),
    dict(id="ti-zit-road", kind="road-block", en="Slide debris between Nyin Maw and Ti Zit", mm="ညင်းမော်–တီဇစ်လမ်း",
         between=["nyin-maw", "ti-zit"], line=13, day=29,
         text="Earth and rock from the slides of 26 Sep block the hill road from Nyin Maw over to Ti Zit; residents "
              "want it cleared so the village can be reached.",
         match_note="Placed midway between Nyin Maw and Ti Zit, then moved onto the nearest MIMU road."),
    dict(id="shin-maw-bridges", kind="bridge-out", en="Bridges down on the road to Shin Maw", mm="ရှင်မော်လမ်း တံတားများ",
         at="kyauk-wut-pyin", line=34, day=29,
         text="Many bridges are destroyed on the road from Kyauk Ni Maw down to Shin Maw.",
         match_note="Placed at Kyauk Wut Pyin, on that road; the posts do not say which bridges."),
    dict(id="aw-gyi-road", kind="flooded-road", en="Myeik–Tanintharyi road under water", mm="မြိတ်-တနင်္သာရီလမ်း",
         at="aw-gyi", line=54, day=29,
         text="The rising river is over the road at Aw Gyi and U Yin Kwin, travellers say."),
    dict(id="lel-taung-yar-road", kind="flooded-road", en="Tanintharyi–Kawthoung road 5 ft under",
         mm="တနင်္သာရီ-ကော့သောင်းလမ်း", at="lel-taung-yar", line=55, day=29,
         text="About 5 ft of water on the road at Lel Taung Yar; vehicles cannot pass and motorcycles cross on rafts."),
    # military movements the posts report alongside the disaster
    dict(id="kyauk-sin-troops", kind="troops", en="Junta troops at Kyauk Sin", mm="ကျောက်ဆင်",
         at="kyauk-sin", line=218, day=28,
         text="About 100 junta troops entered Kyauk Sin village tract, which includes landslide-hit Kayin Gyi. They "
              "said they had come to help but stayed at Kyauk Sin, and residents fled."),
    dict(id="sez-troops", kind="troops", en="Junta column in the Dawei SEZ", mm="ရလိုင်၊ ပုဂေါဇွန်း၊ သစ်တို့ထောင့်",
         at="ya-laing", line=248, day=28,
         text="A column of about 300 has been in Ya Laing, Pu Gaw Zun and Thit Toe Htaung, in the Dawei Special "
              "Economic Zone, since 23 Sep, after a clash near Pein Shaung on 25 Sep. Residents fled into the storm. "
              "Resistance forces say they have pulled back to avoid fighting during the disaster.",
         match_note="Placed at Ya Laing, the first of the three villages named."),
]

# The rescue convoy's progress. `at` = site or incident id; `mode` = how the leg into
# this point was travelled.
RESCUE = [
    dict(at="dawei-town", day=27, t="27 Sep, early morning", line=548, mode="road",
         en="Emergency rescue teams leave Dawei for Launglon."),
    dict(at="ka-myaw-gyi", day=27, t="27 Sep, to 9:30 am", line=716, mode="road", stop=True,
         en="Held up by flooding at Ka Myaw Gyi; the red-level villages are out of reach."),
    dict(at="tha-byar", day=27, t="27 Sep, ~11 am", line=624, mode="road",
         en="Reach Tha Byar and clear slide debris from the road near Pyin Sa Thi Maw and the monastery."),
    dict(at="launglon-town", day=27, t="27 Sep, midday", line=529, mode="road",
         en="Reach Launglon town."),
    dict(at="poe-zar-pin", day=27, t="27 Sep, 2:30–4:30 pm", line=531, mode="road", stop=True,
         en="Stopped by the Poe Zar Pin slide. The detour is flooded; the teams appeal for backhoes and "
            "tractors to dig through."),
    dict(at="ka-det-nge-htein", day=28, t="28 Sep, ~8 am", line=397, mode="foot",
         en="An advance team walks round the slide on forest paths and reaches Kadet Nge Htein; search and "
            "rescue begins."),
    dict(at="auk-yay-phyu", day=28, t="28 Sep", line=389, mode="foot", stop=True,
         en="Furthest point reached. Villages further south, Taw Kye, Tha Kyet Taw, Ra Be, Za Lut and Nyaw "
            "Pyin, have had no help."),
    # `frm`: the leg into this point starts there, not at the previous entry
    dict(at="nyin-maw", frm="poe-zar-pin", day=29, t="29 Sep", line=30, mode="road",
         en="Backhoes have cleared the road as far as Nyin Maw, the teams' base and supply point since 28 Sep. "
            "Kyauk Ni Maw and the villages beyond still have no rescue team."),
]

# `t` orders events and places them on the rain chart; `when` is what the text says.
TIMELINE = [
    dict(t="2026-09-25T18:00", when="25 Sep, evening", area="Launglon", line=661, kind="landslide",
         site="kyet-hlut", en="Hills in southern Launglon begin collapsing, as far as Kyet Lut."),
    dict(t="2026-09-26T08:00", when="26 Sep, morning", area="Launglon", line=726, kind="rain",
         en="Heavy rain sets in over Launglon and keeps falling into the night."),
    dict(t="2026-09-26T17:00", when="26 Sep, ~5 pm", area="Launglon", line=664, kind="landslide",
         site="kyauk-ni-maw", en="A landslide buries houses and people at Kyauk Ni Maw."),
    dict(t="2026-09-26T17:30", when="26 Sep, ~5 pm", area="Launglon", line=728, kind="access",
         en="People push motorcycles through floodwater on tractors; by night every road is under water and "
            "the bridges are submerged."),
    dict(t="2026-09-26T18:00", when="26 Sep, 6 pm", area="Launglon", line=747, kind="rescue",
         site="kyauk-ni-maw", en="Villagers pull an elderly person and two children from the slide at Kyauk Ni "
                                 "Maw; the ground is still moving."),
    dict(t="2026-09-26T21:00", when="26 Sep, ~9 pm", area="Launglon", line=615, kind="landslide",
         site="kayin-gyi", en="First slide at Kayin Gyi."),
    dict(t="2026-09-26T22:00", when="26 Sep, night", area="Launglon", line=729, kind="flood",
         en="Families in low-lying Launglon homes move out in the dark."),
    dict(t="2026-09-27T00:00", when="27 Sep, ~midnight", area="Thayetchaung", line=636, kind="flood",
         site="kin-shey", en="Water starts entering houses in Kin Shey; by dawn the ground floors are under."),
    dict(t="2026-09-27T02:00", when="27 Sep, ~2 am", area="Launglon", line=615, kind="landslide",
         site="kayin-gyi", en="Second slide at Kayin Gyi; nearly 30 houses buried."),
    dict(t="2026-09-27T07:00", when="27 Sep, morning", area="Dawei", line=502, kind="flood",
         site="dawei-town", en="Water starts entering wards of Dawei town."),
    dict(t="2026-09-27T08:00", when="27 Sep, morning", area="Dawei", line=429, kind="flood",
         site="pa-kar-ri", en="Water enters Pa Kar Ri on the border road; residents start moving out."),
    dict(t="2026-09-27T08:30", when="27 Sep, morning", area="Thayetchaung", line=518, kind="flood",
         site="taung-pyauk", en="Floods begin in the Taung Pyauk area."),
    dict(t="2026-09-27T09:30", when="27 Sep, 9:30 am", area="Launglon", line=719, kind="access",
         site="ka-myaw-gyi", en="Rescue teams are held at Ka Myaw Gyi by floodwater; four red-level villages "
                                "are out of reach."),
    dict(t="2026-09-27T10:00", when="27 Sep, morning", area="Launglon", line=530, kind="landslide",
         site="poe-zar-pin", en="Poe Zar Pin hill collapses onto the road between Launglon and Nyin Maw."),
    dict(t="2026-09-27T11:00", when="27 Sep, ~11 am", area="Launglon", line=624, kind="rescue",
         site="tha-byar", en="Rescue teams reach Tha Byar and clear slide debris."),
    dict(t="2026-09-27T12:00", when="27 Sep, 12 noon", area="Launglon", line=630, kind="toll",
         en="Three bodies recovered in Launglon; tens missing. Slides continue on the western hills."),
    dict(t="2026-09-27T12:30", when="27 Sep, midday", area="Launglon", line=647, kind="toll",
         site="min-yat", en="Mother's body recovered at Min Yat; her child is found alive."),
    dict(t="2026-09-27T13:00", when="27 Sep, midday", area="Launglon", line=553, kind="comms",
         site="kyauk-ni-maw", en="Contact with Kyauk Ni Maw is lost."),
    dict(t="2026-09-27T14:30", when="27 Sep, ~2:30 pm", area="Launglon", line=548, kind="access",
         site="poe-zar-pin", en="The Poe Zar Pin slide stops the rescue convoy heading south."),
    dict(t="2026-09-27T15:00", when="27 Sep, 3 pm", area="District", line=590, kind="rain",
         en="Strong winds sweep Dawei District; the rain does not let up."),
    dict(t="2026-09-27T15:30", when="27 Sep, 3:30 pm", area="Thayetchaung", line=598, kind="flood",
         site="thin-kyun", en="Water on the Dawei–Myeik road at Thin Kyun drops by about 2 ft."),
    dict(t="2026-09-27T16:30", when="27 Sep, 4:30 pm", area="Launglon", line=531, kind="access",
         site="poe-zar-pin", en="Rescue teams still stuck at the slide; they appeal for backhoes and tractors."),
    dict(t="2026-09-27T18:00", when="27 Sep", area="Dawei", line=510, kind="rain",
         en="DMH: 11.02 in (280 mm) of rain at Dawei, the highest on record. The old record, 9.68 in, dated "
            "from 1998."),
    dict(t="2026-09-27T19:00", when="27 Sep, evening", area="Dawei", line=505, kind="rescue",
         site="ka-nyon-ward", en="Ten people, including elderly people and a child, rescued from rising water "
                                 "near Taik Thit monastery. Power is cut to the whole town."),
    dict(t="2026-09-27T19:30", when="27 Sep, evening", area="Tanintharyi", line=413, kind="comms",
         site="tanintharyi-town", en="Phone and internet lines go down across Tanintharyi Township."),
    dict(t="2026-09-27T21:00", when="27 Sep, night", area="Launglon", line=416, kind="landslide",
         site="kayin-gyi", en="Another slide buries the whole eastern half of Kayin Gyi."),
    dict(t="2026-09-27T21:30", when="27 Sep, night", area="Dawei", line=431, kind="flood",
         site="pa-kar-ri", en="Low-lying houses in Pa Kar Ri are completely submerged."),
    dict(t="2026-09-27T22:00", when="27 Sep", area="Launglon", line=386, kind="toll", site="nyaw-pyin",
         approx=True, en="A landslide at Nyaw Pyin kills two women (reported on 28 Sep)."),
    dict(t="2026-09-28T05:30", when="28 Sep, early morning", area="Launglon", line=396, kind="rescue",
         site="poe-zar-pin", en="An advance rescue team leaves the road and walks round the slide through "
                                "the forest."),
    dict(t="2026-09-28T07:00", when="28 Sep, morning", area="Dawei", line=489, kind="flood",
         site="bon-maw-ward", en="Single-storey houses under water in five Dawei wards."),
    dict(t="2026-09-28T08:00", when="28 Sep, ~8 am", area="Launglon", line=397, kind="rescue",
         site="ka-det-nge-htein", en="The advance team reaches Kadet Nge Htein and starts searching."),
    dict(t="2026-09-28T09:00", when="28 Sep, morning", area="Region", line=497, kind="forecast",
         en="DMH: the low off the Tanintharyi coast may become a depression within 24 hours, moving north "
            "and north-west towards the Ayeyarwady delta."),
    dict(t="2026-09-28T09:30", when="28 Sep, morning", area="Launglon", line=391, kind="comms",
         site="nyaw-pyin", en="No contact with Nyaw Pyin: phone and internet are down."),
    dict(t="2026-09-28T10:00", when="28 Sep, morning", area="Launglon", line=422, kind="toll",
         en="At least five bodies recovered in Launglon; dozens still missing. Rescuers have not reached "
            "Kadet Nge [Htein], Ti Zit or Za Lut."),
    dict(t="2026-09-28T11:00", when="28 Sep", area="Thayetchaung", line=482, kind="access",
         site="ka-nyin-chaung", approx=True,
         en="The Ka Nyin Chaung bridge on Union Road No. 8 is destroyed; the Dawei–Myeik road is cut."),
    dict(t="2026-09-28T12:00", when="28 Sep, 12 noon", area="Launglon", line=399, kind="access",
         site="poe-zar-pin", en="The rest of the rescue force is still clearing earth from the Launglon–Nyin "
                                "Maw road."),
    dict(t="2026-09-28T12:30", when="28 Sep", area="Tanintharyi", line=407, kind="flood", site="tha-kyet",
         approx=True, en="After three days of rain, villages on the Tanintharyi River begin to flood."),
    dict(t="2026-09-28T13:00", when="28 Sep", area="Launglon", line=389, kind="access", site="auk-yay-phyu",
         approx=True, en="The rescue team has got no further than Auk Yay Phyu; villages to the south have "
                         "had no help."),
    # ---- 29 Sep update
    dict(t="2026-09-26T19:30", when="26 Sep, night", area="Launglon", line=263, kind="toll",
         site="ka-det-nge-htein", approx=True, en="Thirteen people go missing in the Kadet Nge Htein slide."),
    dict(t="2026-09-26T20:00", when="26 Sep", area="Launglon", line=99, kind="landslide", site="nyaw-pyin",
         approx=True, en="At Nyaw Pyin the hill 'roars like an aeroplane', then collapses; neighbours dig out an "
                         "old woman. (A 28 Sep post dates the deaths here to 27 Sep.)"),
    dict(t="2026-09-26T20:30", when="26 Sep, night", area="Launglon", line=11, kind="landslide", site="ti-zit",
         approx=True, en="Hills round Ti Zit collapse, burying the village's streets and the hill road out."),
    dict(t="2026-09-26T21:00", when="26 Sep, ~9 pm", area="Launglon", line=374, kind="flood", site="way-di",
         en="Water starts rising at Way Di; the road to Kone Zayat goes nearly 5 ft under and about 20 cattle "
            "are swept away."),
    dict(t="2026-09-26T22:30", when="26 Sep, night", area="Launglon", line=85, kind="landslide", site="thea-pon",
         approx=True, en="Inwa hill slides onto the monastery at Thea Pon."),
    dict(t="2026-09-27T15:00", when="27 Sep", area="Launglon", line=364, kind="landslide", site="pa-nyit",
         approx=True, en="Slides at Pa Nyit bury two houses and cut the road either side of the village."),
    dict(t="2026-09-27T16:00", when="27 Sep, ~4 pm", area="Dawei", line=282, kind="comms", site="dawei-town",
         en="Electricity is cut across the district's flooded areas."),
    dict(t="2026-09-27T22:00", when="27 Sep, night", area="Dawei", line=276, kind="rescue", site="ka-nyon-ward",
         en="Residents of seven Dawei wards are moved out overnight to monasteries."),
    dict(t="2026-09-28T12:00", when="28 Sep, from midday", area="District", line=358, kind="rain",
         en="Rain stops over Dawei, Launglon and most other places; the water starts to fall."),
    dict(t="2026-09-28T14:00", when="28 Sep, afternoon", area="Launglon", line=265, kind="toll",
         site="ka-det-nge-htein", en="The Zambu Thiri team recovers the bodies of a 12-year-old boy and a monk; five "
                                     "dead at Kadet Nge Htein."),
    dict(t="2026-09-28T15:00", when="28 Sep, afternoon", area="Thayetchaung", line=37, kind="recede",
         site="thayetchaung-town", en="Water falls in Thayetchaung; the clean-up of mud and fallen trees begins."),
    dict(t="2026-09-28T16:00", when="28 Sep", area="Launglon", line=383, kind="toll",
         en="Dawei Watch's Launglon count reaches nine dead; dozens missing."),
    dict(t="2026-09-28T17:00", when="28 Sep, evening", area="Launglon", line=286, kind="toll", site="ka-det-gyi",
         en="The bodies of a mother and son are found under slide earth in their orchard at Kadet Gyi."),
    dict(t="2026-09-28T18:00", when="28 Sep, evening", area="Launglon", line=371, kind="recede",
         site="launglon-town", en="Water falls in Launglon town, Ka Myaw Gyi, Way Di, Min Yat and Tha Byar."),
    dict(t="2026-09-28T18:30", when="28 Sep", area="Dawei", line=352, kind="rain",
         en="DMH: 13.62 in (346 mm) of rain at Dawei, beating the day-old record."),
    dict(t="2026-09-28T19:00", when="28 Sep, evening", area="Thayetchaung", line=137, kind="toll",
         en="Six dead in Thayetchaung Township and two swept away."),
    dict(t="2026-09-28T19:30", when="28 Sep, evening", area="Launglon", line=271, kind="toll",
         en="The Launglon count reaches twelve dead."),
    dict(t="2026-09-29T07:00", when="29 Sep, morning", area="Dawei", line=110, kind="recede", site="bon-maw-ward",
         en="Water falls in Dawei's wards; the sun comes out and people go home to clean up."),
    dict(t="2026-09-29T09:00", when="29 Sep, morning", area="Launglon", line=119, kind="toll", site="tha-byar",
         en="A mother and son at Tha Byar are still missing after three days."),
    dict(t="2026-09-29T10:00", when="29 Sep", area="Launglon", line=30, kind="rescue", site="nyin-maw",
         approx=True, en="Backhoes have cleared the road as far as Nyin Maw; Kyauk Ni Maw is days away."),
    dict(t="2026-09-29T12:00", when="29 Sep, midday", area="District", line=59, kind="toll",
         en="Dawei Watch counts 23 dead in three townships (15 in Launglon, 6 in Thayetchaung, 2 in Dawei), with "
            "dozens missing."),
    dict(t="2026-09-29T12:30", when="29 Sep, midday", area="Dawei", line=114, kind="comms", site="dawei-town",
         en="Dawei town has now had no electricity since 27 Sep."),
    dict(t="2026-09-29T15:00", when="29 Sep, ~3 pm", area="Tanintharyi", line=49, kind="flood",
         site="tanintharyi-town", en="The Tanintharyi River passes 26 ft, over 2 ft above its 24 ft danger mark."),
    dict(t="2026-09-29T16:00", when="29 Sep", area="Tanintharyi", line=55, kind="access", site="lel-taung-yar",
         approx=True, en="5 ft of water on the Tanintharyi–Kawthoung road; motorcycles cross on rafts."),
]

QUOTES = [
    dict(site="kyauk-ni-maw", line=747, by="Kyauk Ni Maw resident, a man, 26 Sep",
         mm="အိမ်တွေ လမ်းတွေ မြေဖုံးကုန်ပြီ။ အသက်ကြီး တစ်ယောက်ကိုလည်း ကျွန်တော်တို့ သွားခေါ်ထုတ်ထားတယ်။ မြေဖုံးနေတဲ့ ကလေး နှစ်ယောက်ကိုလည်း လောလောဆယ် ကယ်ထုတ်ထားတယ်။ မြေကအခုအထိ ဆက်ပြိုနေတုန်း အရေးပေါ်အကူအညီတွေ လိုနေတယ်",
         en="Houses and roads are buried. We went and brought out an old person, and we've pulled out two "
            "children who were buried. The ground is still collapsing. We need emergency help."),
    dict(site="sit-pyay", line=730, by="Sit Pyay resident, 26 Sep",
         mm="တစ်ရွာလုံးလည်း ပင်လယ်ပြင်ကြီးလိုဖြစ်သွားပြီ။ လူတွေလည်း ညမအိပ်ရဲကြဘူး။ တောင်ပြိုမှာကြောက်နေကြတယ်",
         en="The whole village has turned into an open sea. People don't dare sleep at night. They're afraid "
            "of landslides."),
    dict(site="ka-det-nge-htein", line=656, by="Kadet Nge [Htein] resident, 27 Sep",
         mm="သေတဲ့သူတွေ မနည်းဘူး။ နှစ်လောင်းပဲ ထုတ်လို့ရသေးတယ်",
         en="So many are dead. We've only been able to bring out two bodies."),
    dict(site="poe-zar-pin", line=533, by="Zambu Thiri rescue team member, 27 Sep",
         mm="ဒါကြောင့် ပိတ်မိနေတဲ့ မြေကြီးကိုပဲတူးပြီး ကျွန်တော်တို့ ဆက်သွားဖို့ စီစဉ်နေတယ်။ ဘက်ဟိုးတွေလည်း အကူအညီတောင်းထားတယ်",
         en="So we're planning to dig through the earth that's blocking us and carry on. We've asked for "
            "backhoes too."),
    dict(site="kin-shey", line=637, by="Kin Shey resident, a woman, 27 Sep",
         mm="တစ်သက်နဲ့တစ်ကိုယ် တစ်ခါမှ မမြင်ဖူးဘူး။ ကျွန်မတို့ရွာမှာ ရေတက်လာလည်း ဒူးဆစ်လောက်ပဲ တက်ဖူးတယ်။ အခုက လူတစ်ရပ်လောက်အထိ မြုပ်တယ်။",
         en="I've never seen anything like it in my life. When water rose in our village it only ever came "
            "up to the knee. Now it's over a person's height."),
    dict(site="thin-kyun", line=598, by="Thin Kyun resident, a man, 3:30 pm 27 Sep",
         mm="ကားကြီးတွေတော့ သွားလို့ရပေမဲ့ ကားငယ်တွေနဲ့ ဆိုင်ကယ်တွေတော့ ဖြတ်ဖို့မလွယ်ဘူး။ အခု (ညနေ ၃ နာရီခွဲ) တော့ ရေ ၂ ပေလောက် ပြန်ကျသွားပြီ",
         en="Big vehicles can get through, but it's hard for small cars and motorbikes. Now (3:30 pm) the "
            "water has dropped about two feet."),
    dict(site="taung-pyauk", line=522, by="Taung Pyauk area resident, 27 Sep",
         mm="လူတွေတော့ အန္တရာယ် မရှိဘူးဗျ။ ကျွဲနွားတော့ ဆုံးရှုံးတယ်ဗျ",
         en="The people are safe. But we've lost buffalo and cattle."),
    dict(site="kyauk-maw-ward", line=503, by="Kyauk Maw ward resident, Dawei, 27 Sep",
         mm="ရေမဝင်တဲ့နေရာ မရှိတော့ဘူး။ ရေဝင်နည်းတာနဲ့ ရေဝင်များတာပဲကွာတယ်။ အရင်က ရေမဝင်ဖူးတဲ့နေရာတွေတောင် ခြေမျက်စိနားလောက် ရေရောက်နေတယ်",
         en="There's nowhere the water hasn't got in. The only difference is how much. Even places that never "
            "flooded have water up to the ankle."),
    dict(site="dawei-town", line=495, by="Dawei resident, morning of 28 Sep",
         mm="လျှပ်စစ်မီးလည်း မလာသေးဘူး ။ မိုးလည်းရွာနေသေးတယ် ။ ညကထက်စာရင်တော့ မိုးရွာ နည်းနည်းလျော့တယ် ။ ညက တစ်ညလုံးစိမ်ပြီး ရွာလိုက်တာ ရေအတိုးမြန်လို့ မအိပ်ဘဲစောင့်ကြည့်ခဲ့ရတယ်",
         en="Still no electricity, and it's still raining, a little less than last night. It poured all night "
            "and the water rose so fast we stayed up watching it."),
    dict(site="pa-kar-ri", line=432, by="Pa Kar Ri resident, night of 27 Sep",
         mm="မြေနိမ့်ပိုင်းတွေ လူအရပ် မမီတော့ဘူး",
         en="In the low-lying parts the water is over a person's head."),
    dict(site="kayin-gyi", line=418, by="Kayin Gyi resident, a man, 28 Sep",
         mm="အရှေ့ပိုင်းတစ်ခြမ်းစာ မြေဖုံးသွားပြီး တံတားနားက လမ်းပိုင်းလည်း ပြတ်သွားတယ်",
         en="The whole eastern half is buried under earth, and the road by the bridge is cut."),
    dict(site="tha-kyet", line=409, by="Tha Kyet resident, Tanintharyi, 28 Sep",
         mm="ညကတည်းက ချောင်း‌‌ရေလျှံတယ်။ စမြုပ်နေပြီ နည်းနည်းမြင့်တဲ့ အိမ်တွေလောက်ကျန်ပြီ",
         en="The stream has been overflowing since last night. It's going under; only the slightly higher "
            "houses are left."),
    dict(site="ka-det-nge-htein", line=398, by="Search-and-rescue official, 28 Sep",
         mm="ရှာဖွေ ကယ်ဆယ်ရေးတွေ စလုပ်နေပြီပေါ့နော်။ အခုအထိတော့ ပိတ်မိနေသူတွေကို ရှာဖွေတာတွေ လုပ်ဆောင်နေပါတယ်။ အသေးစိတ် စာရင်းအတိအကျတော့ တက်မလာ သေးဘူး",
         en="Search and rescue has started. We're still looking for the people who are trapped. We don't have "
            "an exact list yet."),
    dict(site="nyaw-pyin", line=389, by="DDMSC information officer, 28 Sep",
         mm="အကူအညီက လုံးဝမရသေးဘူး။ ထားဝယ်က ဆင်းလာကူညီတဲ့အဖွဲ့ကလည်း အောက်ရေဖြူအထိပဲ ရောက်သေးတယ်။ အောက်ဘက်ရွာတွေအထိ ရောက်အောင် အတော်ဆင်းရဦးမယ်။",
         en="There's been no help at all. The team that came down from Dawei has only got as far as Auk Yay "
            "Phyu. It'll take a lot to reach the villages further south."),
    # ---- 29 Sep update
    dict(site="way-di", line=377, by="Way Di resident, a man, 28 Sep",
         mm="လမ်းမမှာ ရေက နည်းနည်းပဲကျန်ပြီ။ လယ်ထဲတော့ ရှိသေးတယ်။ ဝါးတင်တဲ့ ထော်လာဂျီတွေ သွားနေကြပြီ",
         en="There's only a little water left on the road. The fields are still flooded. The tractors carrying "
            "bamboo are moving again."),
    dict(site="thayetchaung-town", line=349, by="Myat Parami charity member, Thayetchaung, 28 Sep",
         mm="ကိုယ့်မြို့ထဲမှာ ဖြစ်နေတာကို ကိုယ်မကယ်နိုင်ဘဲ ဖြစ်နေတယ်။ အဓိကတော့ လှေမရှိတဲ့ဒဏ်ပေါ့။",
         en="It's happening in our own town and we can't rescue people. Above all, we have no boats."),
    dict(site="kyar-inn", line=330, by="Kyar Inn resident, a woman, 28 Sep",
         mm="တစ်ရွာလုံးက အထဲမှာ ပိတ်မိနေကြတာပါရှင်။ တစ်ယောက်မှ ထွက်မရဘူး",
         en="The whole village is trapped inside. Not one person can get out."),
    dict(site="ka-det-gyi", line=289, by="Villager who dug out the bodies, Kadet Gyi, 28 Sep",
         mm="ဒီနေ့မှ သူတို့ခြံထဲ ဝင်ရှာကြတာ ခြံတစ်ခြံလုံးက တောင်ပြိုမြေတွေနဲ့ ပြည့်နေပြီ အလောင်းကို မနည်းဖော်ထုတ်လာရတယ်",
         en="Only today could we go into their orchard to look. The whole orchard was full of slide earth; it took "
            "a lot to dig the bodies out."),
    dict(site="dawei-town", line=278, by="U Naing Myo Thwin, Tanintharyi Region emergency rescue team, 28 Sep",
         mm="စပြီး ကယ်ထုတ်လာကတည်းက တချို့က အဝတ်အထည်တွေ ယူချိန်မရတဲ့သူတွေ ရှိတယ်။",
         en="Since we started bringing people out, some of them had no time to take any clothes."),
    dict(site="ka-det-nge-htein", line=270, by="Kadet Nge Htein resident, 28 Sep",
         mm="လုံးဝပျက်စီးတာ ၃၁ ဆောင်။ မြေဝင်ဖုံးနေတာက အားလုံး ဘောလုံးကွင်း ငါးကွင်းစာလောက်ရှိတယ်။",
         en="Thirty-one houses completely destroyed. The earth covers about five football pitches in all."),
    dict(site="lay-hnya", line=183, by="Lay Hnya resident, a man, 28 Sep",
         mm="မိုးကအခုခဏပြတ်နေပေမဲ့ ဆက်ရွာရင် ရေဆက်လက်တက်လာနိုင်လို့ မြစ်ချောင်းနံဘေးနေထိုင်သူတွေအားလုံး ကြိုတင်ပြင်ပြီး သတိထားဖို့လိုလိမ့်မယ်",
         en="The rain has stopped for now, but if it starts again the water could keep rising, so everyone living "
            "by the rivers and streams needs to get ready and stay alert."),
    dict(site="nyaw-pyin", line=99, by="Nyaw Pyin resident, interviewed on the night of 28 Sep",
         mm="တောင်မပြိုခင်မှာ တောင်အော်တယ်လို့ သူကပြောပြတယ်။ လေယာဥ်ပျံအသံလိုမျိုး အသံကြမ်းတယ်ပေါ့။ တစ်ရွာလုံးဟိန်းသွားတယ်တဲ့။",
         en="He said the hill roared before it fell. A harsh sound, like an aeroplane. The whole village rang "
            "with it."),
    dict(site="tha-byar", line=120, by="Neighbour of the missing mother and son, a woman, 29 Sep",
         mm="သူ့ဘဝလည်း သနားစရာ။ ထောင်ကနေ လွတ်လာတာ သုံးနှစ်တောင် မပြည့်သေးဘူး။ မိသားစုနဲ့ ပြန်ဆုံရတာ ခဏလေးပဲ ရှိသေးတယ်",
         en="His life is so sad. He's been out of prison less than three years; he'd only just got back to his "
            "family."),
    dict(site="ta-ku", line=76, by="Tanintharyi Township resident, 29 Sep",
         mm="ရေက တက်လာတာ သုံးရက်အတွင်း တော်တော်မြန်တယ်။ ထားဝယ်ဘက်က ရေတွေ ဆင်းလာလို့လည်း ပါမယ်ထင်တယ်။",
         en="The water has come up very fast in three days. I think it's partly the water coming down from "
            "Dawei."),
    dict(site="tanintharyi-town", line=51, by="Tanintharyi town resident, 29 Sep",
         mm="ဒီမှာ မနေ့ကတည်းက မိုးတိတ်နေပေမဲ့ ထားဝယ်ဘက်က ရေဆင်းလာတော့ မြစ်ရေတိုးလာတာ",
         en="The rain stopped here yesterday, but the water coming down from the Dawei side is raising the "
            "river."),
    dict(site="kyauk-ni-maw", line=26, by="Kyauk Ni Maw villager coordinating aid from outside, 29 Sep",
         mm="ရွာထဲ ကျန်နေတဲ့လူတွေချည်းပဲ လက်နဲ့ ရှင်းလင်းရှာဖွေနေရတာပေါ့။ ဘက်ဟိုးလည်း မရှိ၊ ဘာယန္တရားမှလည်း မရှိ",
         en="It's only the people left in the village clearing and searching, by hand. No backhoe, no machinery "
            "at all."),
    dict(site="ti-zit", line=14, by="Ti Zit resident, 29 Sep",
         mm="အခု တာဝါတိုင်မှာရှိနေတဲ့ ဆီကုန်ရင် ဆက်သွယ်ရေးလည်း ရတော့မှာ မဟုတ်ဘူး။ လောလောဆယ်တော့ ရွာက ဈေးဆိုင်တွေမှာ ရှိတဲ့ ရိက္ခာတွေနဲ့ပဲ စားနေသောက်နေကြရပါတယ်။ ဒါကုန်ရင် မရှိတော့ဘူး",
         en="When the fuel at the phone tower runs out, we'll lose contact too. For now we're living on what the "
            "village shops had. When that's gone, there's nothing."),
]

# Township-level figures and the storm. `line` = source line.
FACTS = dict(
    record_in=11.02, record_mm=280, prev_record_in=9.68, prev_record_year=1998, record_line=606,
    sept_mean_mm=707, sept_mean_by="WMO climate normal quoted in the explainer", sept_mean_line=463,
    national_daily_mean_mm=30, national_line=605,
    forecast_3day_mm=[360, 470], forecast_by="U Win Naing, weather analyst", forecast_line=589,
    thayetchaung_official=dict(wards=5, depth_ft=[6, 8], affected=18000, line=524,
                               by="military government figures"),
    launglon_villages="20+", launglon_line=421,
    bodies=[  # the Launglon township count as it was reported
        dict(t="2026-09-26T18:00", n=0, line=748, label="26 Sep: people missing, none recovered"),
        dict(t="2026-09-27T12:00", n=3, line=630, label="27 Sep noon: 3 bodies"),
        dict(t="2026-09-28T10:00", n=5, line=422, plus=True, label="28 Sep morning: at least 5 bodies"),
        dict(t="2026-09-28T16:00", n=9, line=383, label="28 Sep: 9 dead"),
        dict(t="2026-09-28T19:30", n=12, line=271, label="28 Sep evening: 12 dead"),
        dict(t="2026-09-29T12:00", n=15, line=61, label="29 Sep midday: 15 bodies recovered"),
    ],
    district_dead=[  # Dawei Watch's count for the whole disaster area
        dict(t="2026-09-28T15:00", n=15, line=193, plus=True, label="28 Sep explainer: at least 15 dead"),
        dict(t="2026-09-29T12:00", n=23, line=59, label="29 Sep midday: 23 dead in three townships"),
    ],
    # the 29 Sep round-up, place by place (lines 61-70)
    toll_29=dict(dead=23, missing_text="dozens", line=59, places=[
        dict(site="ka-det-nge-htein", dead=10, missing=3, line=62),
        dict(site="ka-det-gyi", dead=2, line=63),
        dict(site="nyaw-pyin", dead=2, line=64),
        dict(site="min-yat", dead=1, line=64),
        dict(site="tha-byar", missing=2, line=64),
        dict(site="kyauk-ni-maw", missing=8, line=64),
        dict(site="saw-hpyar", dead=2, line=67),
        dict(site="ka-nyin-chaung", dead=2, line=67),
        dict(site="thayetchaung-town", dead=2, line=67),
        dict(site="kyauk-aing", missing=2, line=68),
        dict(site="pyar-thar-chaung", dead=2, line=70),
    ]),
    record2_in=13.62, record2_mm=346, record2_line=352,
    villages_hit="40+", villages_hit_line=193,
    thayetchaung_villages="20+", thayetchaung_line=66,
    # 17 ft is the alert (စိုးရိမ်) mark and 24 ft the danger (အန္တရာယ်) mark (line 50)
    tanintharyi_river=dict(alert_ft=17, danger_ft=24, line=50, history_line=56, readings=[
        dict(t="2026-09-27T12:00", ft=15, approx=True, line=705, label="27 Sep: about 2 ft below the alert mark"),
        dict(t="2026-09-29T15:00", ft=26, plus=True, line=49, label="29 Sep, ~3 pm: over 26 ft"),
    ], history="In 2026 the river passed its alert mark in July, August and September, and its danger mark in "
               "August and again now."),
    history=[dict(year=1994, line=737, text="Heavy rain brought hills down in Launglon, killing people and "
                                            "destroying hundreds of acres of orchards."),
             dict(year=1997, line=610, text="Launglon residents recall large landslides like these."),
             dict(year=1997, line=368, text="At Pa Nyit a slide buried about 100 houses and 61 people died in the "
                                            "mud, villagers say.")],
    storm=[
        dict(line=442, en="21 Sep: Thailand's meteorological department warns of heavy to very heavy rain, "
                         "flash floods and landslides for 23–27 Sep as a low moves in from central Vietnam."),
        dict(line=451, en="26 Sep: the low, crossing Cambodia and Thailand, meets a strong south-west monsoon "
                         "over the Andaman Sea. Record rain floods Bangkok; heavy rain at Dawei."),
        dict(line=459, en="The Tanintharyi range lifts the moist monsoon air and wrings the rain out on its "
                         "Andaman-facing side (orographic lift)."),
        dict(line=461, en="Hillsides already soaked by the monsoon take in more water than they can hold; pore "
                         "pressure rises and slopes fail."),
        dict(line=497, en="28 Sep: DMH expects the low to strengthen into a depression and move north and "
                          "north-west, across the Gulf of Mottama towards the Ayeyarwady delta."),

        dict(line=352, en="28 Sep: DMH records 13.62 in (346 mm) at Dawei, a second record in two days. Rain "
                          "stops over most of the area from midday."),
        dict(line=361, en="DMH has warned that a strong El Niño set in this September, bringing erratic rain, "
                          "heat, storms and drought."),
    ],
)


# Lifelines: the state of roads, bridges, power, phones, rescue and food supply by
# area, as of the latest post that mentions it. status: cut | disrupted | working |
# needed. `line` is the file line (1-based), like everywhere else in this file.
LIFELINE_COLS = [("road", "Roads"), ("bridge", "Bridges"), ("power", "Power"), ("comms", "Phone and internet"),
                 ("rescue", "Rescue teams"), ("supplies", "Food and water")]
LIFELINES = [
    dict(area="Launglon south", sub="Beyond Nyin Maw", cells=dict(
        road=dict(s="cut", day=29, line=30, t="Backhoes have cleared the road only as far as Nyin Maw. Slides still "
                                              "block the hill road to Ti Zit and nearly every village further "
                                              "south."),
        bridge=dict(s="cut", day=29, line=34, t="Many bridges destroyed on the road from Kyauk Ni Maw down to "
                                                "Shin Maw."),
        comms=dict(s="cut", day=29, line=23, t="Kyauk Ni Maw reachable only through villagers who find a signal; "
                                               "Ti Zit's phone tower is running out of fuel."),
        rescue=dict(s="disrupted", day=29, line=62, t="A dozen-strong advance team at Kadet Nge Htein since 28 Sep; "
                                                      "no team has reached Kyauk Ni Maw, Ti Zit, Za Lut or Nyaw "
                                                      "Pyin."),
        supplies=dict(s="needed", day=29, line=16, t="Ti Zit's 1,000-plus people live on shop stocks; 200-plus at "
                                                     "Kyauk Ni Maw's monastery need food and medicine."))),
    dict(area="Launglon north and town", sub="Ka Myaw Gyi to Nyin Maw", cells=dict(
        road=dict(s="working", day=28, line=372, t="Water fell on the evening of 28 Sep at Ka Myaw Gyi, Way Di, Min "
                                                   "Yat, Tha Byar and in Launglon town."),
        rescue=dict(s="working", day=28, line=159, t="Teams based at Nyin Maw, where relief supplies are collected "
                                                     "and handed out."),
        supplies=dict(s="needed", day=28, line=165, t="Food, clothes and above all drinking water: the slides "
                                                      "wrecked the village wells."))),
    dict(area="Launglon west coast", sub="Maungmagan, Kayin Gyi, Pa Nyit", cells=dict(
        road=dict(s="cut", day=28, line=366, t="Slides on the road either side of Pa Nyit."),
        bridge=dict(s="cut", day=28, line=417, t="Kayin Gyi's bridge and village roads destroyed."),
        comms=dict(s="cut", day=28, line=367, t="Shan Maw, Pein Ne Chaung and Kyone Ga Nan, beyond Pa Nyit, cut "
                                                "off and out of contact."),
        rescue=dict(s="working", day=28, line=157, t="Teams from Maungmagan working the Kayin Gyi and Kan Pa Ni "
                                                     "side."),
        supplies=dict(s="needed", day=28, line=210, t="Kayin Gyi's residents in the monastery, short of food."))),
    dict(area="Dawei town", sub="15 MIMU wards", cells=dict(
        road=dict(s="working", day=29, line=110, t="Water falling in the wards on the morning of 29 Sep; people "
                                                   "back home cleaning up."),
        power=dict(s="cut", day=29, line=114, t="Off since 27 Sep; still off at midday on 29 Sep."),
        comms=dict(s="disrupted", day=28, line=282, t="Some phone lines down until at least the evening of 28 Sep."),
        rescue=dict(s="working", day=28, line=276, t="Residents of seven wards moved out overnight on 27 Sep; the "
                                                     "Red Cross giving health care."),
        supplies=dict(s="needed", day=28, line=274, t="600-plus people in five monasteries need food, clothes and "
                                                      "medicine."))),
    dict(area="East of Dawei", sub="Dawei–Htee Khee road", cells=dict(
        road=dict(s="cut", day=28, line=283, t="Impassable between Byaw Taw Wa and Za Lun on 28 Sep; Pa Kar Ri "
                                               "under water; one lane past a slide at Tha Yet Ngoke."),
        bridge=dict(s="cut", day=28, line=433, t="San Chi bridge under water."),
        supplies=dict(s="needed", day=28, line=227, t="Pa Kar Ri tract villagers in monasteries need food."))),
    dict(area="Thayetchaung", sub="And the Dawei–Myeik road", cells=dict(
        road=dict(s="cut", day=28, line=325, t="Ka Nyin Chaung bridge on Union Road No. 8 destroyed; the "
                                               "Dawei–Myeik road is cut."),
        bridge=dict(s="cut", day=28, line=141, t="Ka Nyin Chaung bridge; two rope bridges at Mei Ke; rope bridges "
                                                 "in the Taung Pyauk area."),
        power=dict(s="cut", day=29, line=37, t="Still off on 29 Sep, after the water fell."),
        comms=dict(s="cut", day=29, line=37, t="Phone lines down because the power is off."),
        rescue=dict(s="cut", day=28, line=348, t="Only a local charity, with no boats; the district's teams are "
                                                 "all in Launglon."),
        supplies=dict(s="needed", day=29, line=43, t="Drinking water, food and clothes, and help clearing silt. "
                                                     "Wells flooded; the town market's food lost."))),
    dict(area="Palaw", sub="Myeik District, south on the highway", cells=dict(
        road=dict(s="disrupted", day=27, line=600, t="Flooded stretches between Palaw, Palauk and Pala; "
                                                     "vehicles stranded."))),
    dict(area="Tanintharyi", sub="Myeik District, on the river", cells=dict(
        road=dict(s="cut", day=29, line=55, t="5 ft of water on the Tanintharyi–Kawthoung road at Lel Taung Yar; "
                                              "the Myeik road under water at Aw Gyi."),
        bridge=dict(s="cut", day=29, line=75, t="Low roads and bridges under water in Ta Ku, Thar Ra Bwin and Thein "
                                                "Daw; people use boats and rafts."),
        comms=dict(s="disrupted", day=29, line=79, t="Phone lines cut, on and off."))),
]


def norm(s):
    return (s or "").replace("​", "").replace(" ", "").strip()


def post_index(lines_text):
    """Headline line numbers, ascending, and the post each belongs to."""
    heads = [i for i, t in enumerate(lines_text, 1) if t.startswith("Dawei Watch")]
    heads = [h - 1 for h in heads]  # the headline is the line before the byline
    return heads


def main():
    text = open(SRC, encoding="utf-8").read().split("\n")
    heads = post_index(text)
    if sorted(p["h"] for p in POSTS) != heads:
        raise SystemExit(f"POSTS headlines {sorted(p['h'] for p in POSTS)} != file {heads}")
    posts = sorted(POSTS, key=lambda p: -p["h"])        # oldest first (bottom of the file)
    for i, p in enumerate(posts, 1):
        p["id"] = f"P{i:02d}"
        p["mm"] = text[p["h"] - 1].strip()
        p["byline"] = text[p["h"]].strip()
        p.setdefault("kind", "News")
    by_head = {p["h"]: p for p in posts}

    def post_of(line):
        k = bisect.bisect_right(heads, line) - 1
        if k < 0:
            raise SystemExit(f"line {line} is before the first post")
        return by_head[heads[k]]

    vp = gpd.read_file(os.path.join(RAW, "village_points_tni.geojson"))
    towns = gpd.read_file(os.path.join(RAW, "town_points.geojson"))
    vt = gpd.read_file(os.path.join(RAW, "adm4_vt_tanintharyi.geojson"))
    wards = gpd.read_file(os.path.join(RAW, "adm5_wards.geojson"))
    bridges = gpd.read_file(os.path.join(RAW, "bridges.geojson"))
    roads = gpd.read_file(os.path.join(RAW, "roads.geojson"))

    # ---------------------------------------------------------------- geocode
    for s in SITES:
        s.setdefault("match", "exact")
        if s["match"] == "unlocated":
            s["lon"] = s["lat"] = None
        elif "town" in s:
            r = towns[towns.Town == s["town"]].iloc[0]
            s.update(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5), pcode=r.Town_Pcode,
                     mimu_name=r.Town + " (town)", mimu_mm=r.Town_MMR4)
        elif "bridge" in s:
            r = bridges[bridges.nmEng == s["bridge"]].iloc[0]
            s.update(lon=round(r.geometry.x, 5), lat=round(r.geometry.y, 5), mimu_name=r.nmEng,
                     mimu_mm=r.nmMya)
        elif "ward" in s or "ward_mm" in s:
            r = (wards[wards.WARD == s["ward"]] if "ward" in s
                 else wards[wards.WARD_MMR.map(norm) == norm(s["ward_mm"])]).iloc[0]
            p = r.geometry.representative_point()
            s.update(lon=round(p.x, 5), lat=round(p.y, 5), pcode=r.WARD_PCODE,
                     mimu_name=r.WARD, mimu_mm=r.WARD_MMR)
        elif "approx_vt" in s:
            names = s["approx_vt"] if isinstance(s["approx_vt"], list) else [s["approx_vt"]]
            rs = vt[vt.VT.isin(names) & (vt.TS == s["ts"])]
            if len(rs) != len(names):
                raise SystemExit(f"{s['id']}: village tracts {names} not all found in {s['ts']}")
            p = rs.geometry.union_all().representative_point()
            s.update(lon=round(p.x, 5), lat=round(p.y, 5), pcode=" ".join(rs.VT_PCODE),
                     mimu_name=" and ".join(rs.VT) + (" (village tracts)" if len(rs) > 1 else " (village tract)"),
                     mimu_mm=" / ".join(rs.VT_MMR))
        else:
            want = norm(s.get("mimu_mm", s["mm"]))
            m = vp[(vp.VLG_MMR.map(norm) == want) & (vp.TS == s["ts"])]
            if "vt_hint" in s:
                m = m[m.VT == s["vt_hint"]]
            if len(m) != 1:
                raise SystemExit(f"{s['id']}: {len(m)} MIMU matches for {want} in {s['ts']}")
            r = m.iloc[0]
            s.update(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5), pcode=str(r.VLG_PCODE),
                     mimu_name=r.VILLAGE, mimu_mm=r.VLG_MMR, vt=r.VT)

    # reference points used by incidents but not themselves reported sites
    extra_pts = {}
    for key, (mm, ts) in {"pyin-htein": ("ပြင်းထိန်", "Launglon"), "kyauk-sin": ("ကျောက်ဆင်", "Launglon"),
                          "ya-laing": ("ရလိုင်", "Yebyu")}.items():
        r = vp[(vp.VLG_MMR.map(norm) == norm(mm)) & (vp.TS == ts)].iloc[0]
        extra_pts[key] = dict(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5))

    # ---------------------------------------------------------------- reports -> daily state
    SEV = {"affected": 0, "severe": 1, "fatal": 2}
    FIG_KEYS = ["dead", "missing", "missing_text", "rescued", "houses", "houses_text", "sheltering",
                "depth_ft", "affected", "villages", "river_ft"]
    for s in SITES:
        for r in s["reports"]:
            p = post_of(r["line"])
            r["post"], r["day"] = p["id"], p["day"]
            r.setdefault("roles", [])
            if not 1 <= r["line"] <= len(text) or not text[r["line"] - 1].strip():
                raise SystemExit(f"{s['id']}: bad line {r['line']}")
        s["reports"].sort(key=lambda r: (r["day"], r["post"]))
        s["first_day"] = s["reports"][0]["day"]
        state = {}
        for d in DAYS:
            rs = [r for r in s["reports"] if r["day"] <= d]
            if not rs:
                state[str(d)] = None
                continue
            figs = {}
            for r in rs:  # later reports overwrite earlier figures
                for k in FIG_KEYS:
                    if k in r:
                        figs[k] = r[k]
            if "missing" in figs and "missing_text" in figs:
                # a later word count ("dozens") supersedes an earlier number, and vice versa
                last_num = max((i for i, r in enumerate(rs) if "missing" in r), default=-1)
                last_txt = max((i for i, r in enumerate(rs) if "missing_text" in r), default=-1)
                figs.pop("missing" if last_txt > last_num else "missing_text")
            rescue = None
            for r in rs:
                if "rescue" in r:
                    rescue = r["rescue"]
            state[str(d)] = dict(
                sev=max((r["sev"] for r in rs), key=SEV.get),
                red=any(r.get("red") for r in rs),
                rescue=rescue,
                roles=sorted({x for r in rs for x in r["roles"]}),
                figs=figs, n=len(rs), new=[r["post"] for r in rs if r["day"] == d],
            )
        s["state"] = state
        last = state[str(DAYS[-1])]
        s["sev"], s["roles"] = last["sev"], last["roles"]

    by_id = {s["id"]: s for s in SITES}
    pts = {**{k: v for k, v in extra_pts.items()}, **{s["id"]: s for s in SITES}}

    for inc in INCIDENTS:
        inc["post"] = post_of(inc["line"])["id"]
        if "between" in inc:
            a, b = (by_id[k] for k in inc["between"])
            mid = Point((a["lon"] + b["lon"]) / 2, (a["lat"] + b["lat"]) / 2)
            near = roads[roads.distance(mid) < 0.03]
            if len(near):
                line = near.geometry.iloc[near.distance(mid).argmin()]
                mid = line.interpolate(line.project(mid))
            inc.update(lon=round(mid.x, 5), lat=round(mid.y, 5), match="approx")
        else:
            p = pts[inc["at"]]
            inc.update(lon=p["lon"], lat=p["lat"], match="approx" if "match_note" in inc else "exact")
    inc_by_id = {i["id"]: i for i in INCIDENTS}

    for r in RESCUE:
        p = by_id.get(r["at"]) or inc_by_id[r["at"]]
        r.update(lon=p["lon"], lat=p["lat"], post=post_of(r["line"])["id"], place=p["en"])
        if "frm" in r:
            f = by_id.get(r["frm"]) or inc_by_id[r["frm"]]
            r["frm_pt"] = [f["lon"], f["lat"]]
    for e in TIMELINE:
        e["post"] = post_of(e["line"])["id"]
        if e.get("site") and e["site"] not in by_id and e["site"] not in inc_by_id:
            raise SystemExit(f"timeline: unknown site {e['site']}")
    for q in QUOTES:
        q["post"] = post_of(q["line"])["id"]
        if norm(q["mm"])[:12] not in norm(text[q["line"] - 1]):
            raise SystemExit(f"quote at line {q['line']} does not match the source text")

    for p in posts:
        p["sites"] = [s["id"] for s in SITES if any(r["post"] == p["id"] for r in s["reports"])]
        p["incidents"] = [i["id"] for i in INCIDENTS if i["post"] == p["id"]]

    def facts_lines(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if (k == "line" or k.endswith("_line")) and isinstance(v, int):
                    yield v
                else:
                    yield from facts_lines(v)
        elif isinstance(o, list):
            for v in o:
                yield from facts_lines(v)
    for n in facts_lines(FACTS):
        if not 1 <= n <= len(text) or not text[n - 1].strip():
            raise SystemExit(f"facts: bad line {n}")
    for t in FACTS["toll_29"]["places"]:
        if t["site"] not in by_id:
            raise SystemExit(f"toll_29: unknown site {t['site']}")
    if sum(t.get("dead", 0) for t in FACTS["toll_29"]["places"]) != FACTS["toll_29"]["dead"]:
        raise SystemExit("toll_29: places do not add up to the round-up's total")

    for row in LIFELINES:
        for c in row["cells"].values():
            if not text[c["line"] - 1].strip():
                raise SystemExit(f"lifeline: bad line {c['line']}")
            c["post"] = post_of(c["line"])["id"]

    grades = {}
    for s in SITES:
        grades[s["match"]] = grades.get(s["match"], 0) + 1

    out = dict(
        source=dict(outlet="Dawei Watch", page="https://web.facebook.com/DaweiWatch",
                    days=["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29"], file=os.path.basename(SRC)),
        posts=posts, facts=FACTS, sites=SITES, references=REFERENCES, incidents=INCIDENTS,
        rescue=RESCUE, lifelines=dict(cols=LIFELINE_COLS, rows=LIFELINES), timeline=sorted(TIMELINE, key=lambda e: e["t"]), quotes=QUOTES,
        match_grades=grades,
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {os.path.relpath(OUT)}: {len(posts)} posts, {len(SITES)} sites, {len(INCIDENTS)} incidents, "
          f"{len(TIMELINE)} timeline entries, {len(QUOTES)} quotes")
    print("match grades:", grades)
    for d in DAYS:
        on = [s for s in SITES if s["state"][str(d)]]
        print(f"  as of {d} Sep: {len(on)} sites, "
              + ", ".join(f"{k} {sum(1 for s in on if s['state'][str(d)]['sev'] == k)}"
                          for k in ("fatal", "severe", "affected")))


if __name__ == "__main__":
    main()

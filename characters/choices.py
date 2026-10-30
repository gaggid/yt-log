"""Predefined choices for every characteristic of a character or a place. They are only suggestions: each field accepts any text the person types, and whatever the person sets is kept when the
chat model fills in the rest (studio.suggest_slots). Values are written the way an image model reads them best: concrete, with colours and lengths."""

INDIAN = ["Indian (North Indian)", "Indian (South Indian)", "Indian (Punjabi)", "Indian (Bengali)", "Indian (Gujarati)", "Indian (Marathi)", "Indian (Tamil)", "Indian (Telugu)",
          "Indian (Kannadiga)", "Indian (Malayali)", "Indian (Rajasthani)", "Indian (Kashmiri)", "Indian (Northeast Indian)", "Indian (Anglo-Indian)"]
ETHNICITY = INDIAN + ["South Asian (Pakistani)", "South Asian (Bangladeshi)", "South Asian (Sri Lankan)", "South Asian (Nepali)", "Middle Eastern", "Arab", "East Asian (Chinese)",
                      "East Asian (Japanese)", "East Asian (Korean)", "Southeast Asian", "African", "Black (African American)", "European (Southern)", "European (Northern)",
                      "Latino", "Central Asian", "Mixed heritage"]
PERSON = {
    "ethnicity": ETHNICITY,
    "gender": ["male", "female"],
    "age": ["8", "14", "18", "22", "25", "28", "32", "38", "45", "55", "65", "75"],
    "build": ["slim", "lean and athletic", "athletic and muscular", "average build", "stocky", "broad and heavy-set", "curvy", "tall and lean", "short and slim", "petite", "tall and broad"],
    "skin": ["fair", "light wheatish", "wheatish", "warm tan", "medium brown", "olive", "dark brown", "deep dark brown", "pale", "rosy fair"],
    "face": ["oval face", "round face with soft cheeks", "square jaw", "long face with high cheekbones", "heart-shaped face", "sharp jawline and defined cheekbones", "soft rounded features",
             "oval face with a short trimmed black beard", "clean-shaven oval face", "face with a light stubble"],
    "hair": ["short black wavy hair", "short black straight hair", "medium-length black hair with a side parting", "long straight black hair", "long black hair in a loose braid",
             "shoulder-length wavy dark brown hair", "black buzz cut", "bald with a neat beard", "curly black hair, short on the sides", "black hair in a high ponytail", "grey short hair",
             "long wavy dark brown hair", "black hair in a bun", "hair covered by a plain scarf",
             "black hair with soft brown and blonde streaks", "dark brown hair with caramel highlights", "black hair with burgundy tips", "black hair with copper balayage from the mid-lengths",
             "dark brown hair with honey blonde face-framing highlights", "natural black hair with a few silver strands"],
    "eyes": ["dark brown", "black", "light brown", "hazel", "green", "blue", "grey", "amber"],
    "top": ["white linen shirt with rolled sleeves", "black fitted t-shirt", "denim jacket over a white t-shirt", "mustard yellow blazer over a grey t-shirt", "navy blazer over a white shirt",
            "olive green bomber jacket over a black t-shirt", "beige trench coat over a black turtleneck", "red hoodie", "oversized grey sweatshirt",
            "white co-ord set crop top", "sage green fitted button-up shirt", "rust-coloured ribbed top", "black leather jacket over a white t-shirt",
            "cream cotton kurta", "maroon silk kurta"],
    "bottom": ["dark blue straight-leg jeans", "black slim trousers", "beige chinos", "light blue wide-leg jeans", "black cargo pants",
               "grey joggers", "black pleated mini skirt", "dark green high-waist trousers", "white co-ord set trousers", "camel-coloured wide-leg pants",
               "cream churidar", "teal silk saree draped in the nivi style"],
    "footwear": ["white sneakers", "brown leather loafers", "black formal shoes", "brown leather sandals", "black boots", "colourful running shoes", "gold juttis", "black heeled sandals", "bare feet"],
    "accessories": ["none", "black wristwatch", "round gold-rimmed glasses", "black rectangular glasses", "silver chain and a black wristwatch", "small gold hoop earrings",
                    "brown leather tote bag", "black cap", "headphones around the neck", "small gold stud earrings", "layered thin gold necklaces",
                    "silver ring on one hand", "canvas tote bag", "thin gold huggie earrings"],
    "expression": ["calm and confident", "warm friendly smile", "calm and tired", "serious and focused", "playful half smile", "curious and alert", "worried", "determined"],
}
PLACE = {
    "ethnicity": ["India (North)", "India (South)", "India (West)", "India (East)", "India (Northeast)", "Rajasthan", "Kerala", "Mumbai", "Delhi", "Kolkata", "Bengaluru", "Hyderabad", "Himalayan region",
                  "Middle East", "East Asia", "Southeast Asia", "Europe", "Africa", "North America", "Latin America"],
    "type": ["modern apartment living room", "rooftop terrace with city skyline", "third-wave coffee shop", "co-working space with glass partitions", "hotel lobby with pendant lights",
             "metro station concourse", "college campus courtyard", "building society gym", "open-plan kitchen-dining room", "balcony with urban view",
             "boutique studio or salon", "busy market street", "beach promenade at dusk", "railway platform", "highway dhaba"],
    "light": ["warm LED panel light from above", "soft diffused daylight through sheer white curtains", "blue hour with warm interior LEDs spilling outside", "neon signs at night",
              "bright overcast midday through floor-to-ceiling windows", "golden hour low sun raking across the room", "track-light spots on a feature wall", "fairy lights at dusk"],
    "size": ["empty and quiet", "quiet with a few people far away", "moderately busy", "crowded", "small and intimate", "wide and open"],
    "materials": ["white painted walls, engineered oak flooring, matte black steel frames",
                  "large-format off-white porcelain tiles, warm grey walls, powder-coated aluminium",
                  "polished concrete floors, exposed brick painted white, pendant brass fixtures",
                  "sage-green walls, blond plywood shelving, woven rattan accents",
                  "glass and brushed steel, pale birch veneer, under-cabinet LED strips",
                  "terrazzo floors, dusty-pink walls, slim white-lacquered furniture"],
}
CHOICES = {"person": PERSON, "place": PLACE}

# Styling: "glamour" is for adult invented characters only (see store.glamour_problem): fashion-editorial, fitted and softly revealing, fully clothed. Quick outfits fill the clothing slots at once.
STYLING = [{"id": "", "label": "Everyday"}, {"id": "glamour", "label": "Glamorous (fitted, softly revealing, tasteful)"}]
OUTFITS = [
    {"id": "g-bodycon", "styling": "glamour", "gender": "female", "label": "Black bodycon mini dress", "top": "black fitted bodycon mini dress with a softly plunging V neckline and thin straps",
     "bottom": "the dress skirt ends mid-thigh", "footwear": "black strappy high heels", "accessories": "small gold hoop earrings and a thin gold necklace", "expression": "a confident half smile with a steady gaze"},
    {"id": "g-offshoulder", "styling": "glamour", "gender": "female", "label": "Off-shoulder crop top and high-waisted skirt", "top": "ivory off-shoulder fitted crop top that bares the shoulders and collarbones",
     "bottom": "high-waisted satin midi skirt with a thigh-high slit in champagne", "footwear": "nude block-heel sandals", "accessories": "gold drop earrings", "expression": "a relaxed, inviting smile"},
    {"id": "g-backless", "styling": "glamour", "gender": "female", "label": "Backless satin halter dress", "top": "emerald satin halter-neck dress with a low open back and a deep V front",
     "bottom": "the dress falls to the floor with a high side slit", "footwear": "gold strappy heels", "accessories": "long gold earrings", "expression": "a calm, sultry gaze with softly parted lips"},
    {"id": "g-saree", "styling": "glamour", "gender": "female", "label": "Chiffon saree with a low-cut backless blouse", "top": "deep red sleeveless backless blouse with a plunging neckline, gold border",
     "bottom": "sheer red chiffon saree draped low on the hips in the nivi style", "footwear": "gold juttis", "accessories": "oxidised silver jhumka earrings and thin bangles", "expression": "a soft, knowing smile"},
    {"id": "g-corset", "styling": "glamour", "gender": "female", "label": "Corset top with high-waist jeans", "top": "black satin corset-style top with a sweetheart neckline",
     "bottom": "high-waisted light blue jeans", "footwear": "white ankle boots", "accessories": "layered gold chains", "expression": "a playful half smile"},
    {"id": "g-beach", "styling": "glamour", "gender": "female", "label": "Beachwear: two-piece with a sheer sarong", "top": "coral two-piece swimsuit with a sheer printed sarong tied at the hip",
     "bottom": "the sarong is tied low on the hips", "footwear": "bare feet", "accessories": "round sunglasses pushed up in the hair", "expression": "a warm, relaxed smile"},
    {"id": "g-shirt", "styling": "glamour", "gender": "male", "label": "Open linen shirt", "top": "white linen shirt unbuttoned to the chest with the sleeves rolled up",
     "bottom": "fitted black trousers", "footwear": "brown leather loafers", "accessories": "thin gold chain", "expression": "a calm, confident gaze with a slight smile"},
    {"id": "g-sleeveless", "styling": "glamour", "gender": "male", "label": "Fitted sleeveless tee", "top": "fitted black sleeveless t-shirt that shows the arms and shoulders",
     "bottom": "dark slim jeans", "footwear": "black boots", "accessories": "black wristwatch", "expression": "a relaxed half smile with a steady gaze"},
    {"id": "g-jacket", "styling": "glamour", "gender": "male", "label": "Open-front leather jacket", "top": "black leather jacket worn open over a bare chest with a thin chain",
     "bottom": "black slim trousers", "footwear": "black boots", "accessories": "silver ring on one hand", "expression": "a serious, smouldering look straight at the camera"},
    {"id": "e-kurta", "styling": "", "gender": "", "label": "Cream cotton kurta", "top": "cream cotton kurta", "bottom": "white pyjama trousers", "footwear": "brown leather sandals",
     "accessories": "none", "expression": "a warm friendly smile"},
    {"id": "e-denim", "styling": "", "gender": "", "label": "Denim jacket and jeans", "top": "denim jacket over a white t-shirt", "bottom": "dark blue jeans", "footwear": "white sneakers",
     "accessories": "none", "expression": "calm and confident"},
]
GLAMOUR_MIN_AGE = 21

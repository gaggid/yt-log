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
             "long wavy dark brown hair", "black hair in a bun", "hair covered by a plain scarf"],
    "eyes": ["dark brown", "black", "light brown", "hazel", "green", "blue", "grey", "amber"],
    "top": ["white linen shirt with rolled sleeves", "black fitted t-shirt", "denim jacket over a white t-shirt", "mustard yellow jacket over a grey t-shirt", "navy blazer over a white shirt",
            "cream cotton kurta", "maroon silk kurta", "olive green bomber jacket over a black t-shirt", "pastel pink kurti with white embroidery", "beige trench coat over a black turtleneck",
            "red hoodie", "teal saree blouse with a gold border", "white shirt with a loosely knotted tie", "oversized grey sweatshirt"],
    "bottom": ["dark blue jeans", "black slim trousers", "beige chinos", "white cotton pyjama trousers", "light blue straight jeans", "black cargo pants", "teal silk saree draped in the nivi style",
               "cream churidar", "grey joggers", "black pleated skirt", "dark green palazzo trousers"],
    "footwear": ["white sneakers", "brown leather loafers", "black formal shoes", "brown leather sandals", "black boots", "colourful running shoes", "gold juttis", "black heeled sandals", "bare feet"],
    "accessories": ["none", "black wristwatch", "round gold-rimmed glasses", "black rectangular glasses", "silver chain and a black wristwatch", "small gold hoop earrings",
                    "brown leather backpack", "red dupatta over one shoulder", "black cap", "thin gold bangles", "headphones around the neck"],
    "expression": ["calm and confident", "warm friendly smile", "calm and tired", "serious and focused", "playful half smile", "curious and alert", "worried", "determined"],
}
PLACE = {
    "ethnicity": ["India (North)", "India (South)", "India (West)", "India (East)", "India (Northeast)", "Rajasthan", "Kerala", "Mumbai", "Delhi", "Kolkata", "Bengaluru", "Hyderabad", "Himalayan region",
                  "Middle East", "East Asia", "Southeast Asia", "Europe", "Africa", "North America", "Latin America"],
    "type": ["railway platform", "rooftop terrace", "narrow old-city lane", "busy market street", "modern cafe", "apartment living room", "beach at sunset", "highway dhaba", "college campus courtyard",
             "metro station", "temple courtyard", "co-working space", "village road with fields", "hotel lobby", "balcony of an apartment"],
    "light": ["golden hour sunlight from low on the left", "blue hour twilight with warm lamps", "soft overcast daylight", "neon signs at night", "warm tungsten indoor light", "harsh midday sun with deep shadows",
              "morning mist with soft sun", "fairy lights at dusk"],
    "size": ["empty and quiet", "quiet with a few people far away", "moderately busy", "crowded", "small and intimate", "wide and open"],
    "materials": ["weathered concrete, steel and green paint", "red brick and wood", "white marble and brass", "glass, steel and pale wood", "sandstone and terracotta", "whitewashed walls and blue doors"],
}
CHOICES = {"person": PERSON, "place": PLACE}

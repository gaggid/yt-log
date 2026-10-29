"""Everyday Indian analogies for explainers and lists (docs/TASKS_quality_overhaul.md task 3.8). An explainer must show the idea as something that happens in a real place with real
objects; the audit's worst film drew an abstract grid and floating platforms. Each entry names the everyday scene, the place it happens in, and the props that make the
comparison visible, so the storyboard has somewhere physical to put an idea."""

BANK = [
    {"id": "kirana_queue", "idea": "a shared limited supply; waiting; rationing", "scene": "customers waiting at a neighbourhood grocery counter while the shopkeeper weighs rice", "place": "a kirana shop", "props": ["brass scales", "jute sacks", "steel containers", "a notebook of accounts"]},
    {"id": "mandi_board", "idea": "prices that rise and fall; supply and demand; averages", "scene": "traders reading a chalk price board at a vegetable market as sacks arrive", "place": "a vegetable mandi", "props": ["chalk price board", "hanging scales", "gunny sacks", "wooden crates"]},
    {"id": "local_train", "idea": "capacity, crowding, a bottleneck, many things moving through one channel", "scene": "a packed local train at a platform with people pushing in and out of the doors", "place": "a railway platform", "props": ["train doors", "platform board", "luggage", "overhead wires"]},
    {"id": "power_cut", "idea": "a hidden dependency; what happens when a system stops", "scene": "a street where all the lights go out and shopkeepers light candles and lamps", "place": "a market lane at dusk", "props": ["candles", "inverter", "dark shops", "a transformer on a pole"]},
    {"id": "wedding_budget", "idea": "limited money, trade-offs, small costs adding up", "scene": "a family around a floor mat adding up wedding costs on a notebook, receipts around them", "place": "a family living room", "props": ["notebook", "receipts", "calculator", "tea glasses"]},
    {"id": "school_notebook", "idea": "records, copying, passing information with small errors", "scene": "a child copying a lesson from the blackboard into a ruled notebook, a mistake crossed out", "place": "a classroom", "props": ["blackboard", "ruled notebook", "pencil", "wooden bench"]},
    {"id": "cricket_scoreboard", "idea": "statistics, rates, probability, chance", "scene": "men gathered under a hand-painted scoreboard at a street match, arguing over the numbers", "place": "a dusty local ground", "props": ["scoreboard with numbers", "bat and ball", "plastic chairs", "spectators"]},
    {"id": "water_tank", "idea": "flow, storage, pressure, something that fills and drains", "scene": "a rooftop tank filling through a pipe while a person checks the float valve", "place": "a rooftop", "props": ["plastic water tank", "pipe", "valve", "ladder"]},
    {"id": "dabba_delivery", "idea": "a reliable chain of hand-offs; routing; error rates", "scene": "lunch boxes handed from cyclist to cyclist along a platform, each marked with a code", "place": "a station platform", "props": ["tiffin boxes", "coded marks", "crates", "cycles"]},
    {"id": "tailor_pattern", "idea": "a pattern copied many times; scaling; templates", "scene": "a tailor tracing a paper pattern onto cloth with chalk, repeating it down a long roll", "place": "a tailor's shop", "props": ["paper pattern", "chalk", "cloth roll", "sewing machine"]},
    {"id": "bus_conductor", "idea": "counting, tickets, a limited number of seats", "scene": "a conductor counting passengers and punching tickets in a crowded bus", "place": "inside a city bus", "props": ["ticket punch", "coins", "handrails", "standing passengers"]},
    {"id": "pressure_cooker", "idea": "pressure building up and being released; thresholds", "scene": "a pressure cooker whistling on a stove in a small kitchen while steam rises", "place": "a home kitchen", "props": ["pressure cooker", "gas stove", "steam", "steel plates"]},
]


def note() -> str:
    """Text for the scene designer of an explainer or a list: where to put an idea that is not a place."""
    rows = [f"- {a['idea']}: {a['scene']} ({a['place']}; {', '.join(a['props'][:3])})" for a in BANK]
    return ("\n\nIDEAS NEED A PLACE. When an idea has no place of its own in the story, show it as an everyday scene in a real Indian place, never as a diagram in empty space, a grid, floating "
            "platforms or symbols. Everyday scenes you can use (adapt them; they are examples of the kind of thing, not a list to copy):\n" + "\n".join(rows))

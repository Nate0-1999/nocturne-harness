"""More walk memories on the TEST palace so the Graph has the M3EX-35 overflow shape."""
import asyncio
from harness.onboarding import load_config
from harness.spine_client import SpineClient, CreateMemoryRequest, MemoryKind, CreateMemoryConflictError

TOPICS = ["amber lanterns", "copper kettles", "velvet curtains", "granite stairs", "cedar shelves",
          "brass compasses", "linen maps", "iron gates", "glass prisms", "silver bells",
          "oak barrels", "clay tablets", "paper cranes", "wool blankets", "jade figurines",
          "tin soldiers", "bamboo flutes", "marble busts", "leather satchels", "coral beads",
          "pewter mugs", "quartz clocks", "ivory keys", "slate roofs", "maple syrup",
          "rope ladders", "canvas tents", "ebony chess sets", "felt hats", "bronze statues",
          "porcelain cups", "ash paddles", "hemp sacks", "opal rings", "willow baskets",
          "zinc buckets", "birch canoes", "cotton kites", "walnut desks", "steel anchors"]
PLACES = ["the north attic", "the east cellar", "the garden shed", "the blue cabinet",
          "the tall wardrobe", "the south porch", "the workshop loft", "the pantry"]

async def main():
    config = load_config()
    assert config.palace_name == "test-m3exf", config.palace_name
    client = SpineClient(config.spine_url, config.spine_token, principal_id=config.principal_id)
    kinds = [MemoryKind.FACT, MemoryKind.PREFERENCE, MemoryKind.PROCEDURE]
    made = 0
    for index, topic in enumerate(TOPICS):
        try:
            await client.create_memory(CreateMemoryRequest(
                principal_id=config.principal_id, label=f"Where the {topic} are",
                body=f"The fictional {topic} are kept in {PLACES[index % len(PLACES)]}.",
                kind=kinds[index % 3], keywords=["fiction", topic.split()[0]],
                editor="m3exf-walk-seed", machine_id=config.machine_id, force=True))
            made += 1
        except CreateMemoryConflictError as exc:
            print("conflict", topic, type(exc.conflict).__name__)
    print("seeded", made)

asyncio.run(main())

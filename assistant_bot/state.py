from collections import defaultdict

conversation_history: dict[int, list[dict[str, str]]] = defaultdict(list)
user_images: dict[int, list[str]] = {}

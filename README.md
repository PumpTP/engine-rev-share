# Engine Rev share page

Opened from the QR on Engine Rev's Share screen in the car. The trip (route, date, distance,
time, fuel, cost, places) rides in the link's `#fragment`, so no server ever sees it. The page
draws a trip card on the phone (OpenStreetMap tiles) and offers Share / Save as PNG.

Link format v1: `#1.<route>.<startMs>.<km×10>.<minutes>.<fuel L×100>.<cost ฿×100>.<places>`,
numbers base 36 (empty = unknown), places base64url UTF-8, route = lat/lon ×1e5 zigzag varint
deltas in 5-bit base64url groups (bit 5 = more). Encoder: `TripShare.pageUrl` in Engine Rev.

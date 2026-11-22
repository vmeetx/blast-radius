"""Turns a set of tests into workers. Milliseconds are whole numbers, as the scorer rounds them."""
import heapq

WORKER_START_MS = 2000


def spread(order, length, count):
    """Longest first onto the emptiest of `count` workers."""
    waiting = [(0, place, []) for place in range(count)]
    for number in order:
        load, place, pile = waiting[0]
        pile.append(number)
        heapq.heapreplace(waiting, (load + length[number], place, pile))
    by_place = sorted(waiting, key=lambda entry: entry[1])
    return [pile for _, _, pile in by_place], [load for load, _, _ in by_place]


def cheapest(chosen, length):
    """(workers, load of each) at the lowest busiest load plus start costs; the fewest workers on a tie."""
    order = sorted(chosen, key=lambda number: (-length[number], number))
    whole = sum(map(length.__getitem__, order))
    winner = None
    for count in range(1, 1 + min(8, len(order))):
        floor = max(length[order[0]], -(-whole // count)) + WORKER_START_MS * count
        if winner is None or floor < winner[0]:
            piles, totals = spread(order, length, count)
            price = WORKER_START_MS * count + max(totals)
            if winner is None or price < winner[0]:
                winner = (price, piles, totals)
    return winner[1:] if winner else ([], [])


def top_up(piles, totals, spare, length):
    """Put each spare test, best first, where it fits most tightly without lengthening the longest worker."""
    ceiling = max(totals, default=0)
    for number in spare:
        room = [(ceiling - load - length[number], which) for which, load in enumerate(totals)]
        fitting = [entry for entry in room if entry[0] >= 0]
        if fitting:
            which = min(fitting)[1]
            piles[which].append(number)
            totals[which] += length[number]
    return piles

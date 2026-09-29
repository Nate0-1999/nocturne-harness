"""SD-073: the ouroboros around the moon — one tapering body, a head with an eye and open
jaws, the tail tip inside its mouth. A 64-unit box; ink and ground are parameters."""
import math
import sys

C, R = 32.0, 21.0
HEAD = -48.0  # degrees, SVG y down: the head sits upper right; the body runs clockwise


def pt(deg, r=R):
    a = math.radians(deg)
    return C + r * math.cos(a), C + r * math.sin(a)


def body_path():
    start, end, n = HEAD + 6, HEAD + 346, 60
    outer, inner = [], []
    for i in range(n + 1):
        t = i / n
        a = start + (end - start) * t
        w = 12.5 - 11.0 * t ** 0.75  # thick neck, thin tail
        outer.append(pt(a, R + w / 2))
        inner.append(pt(a, R - w / 2))
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in outer + inner[::-1]) + " Z"


def mark(ink, ground, moon_opacity="0.75"):
    a = math.radians(HEAD)
    d = (math.sin(a), -math.cos(a))  # counter-clockwise: the way the head faces
    nrm = (math.cos(a), math.sin(a))  # outward
    hx, hy = pt(HEAD, R + 1.4)
    turn = math.degrees(math.atan2(d[1], d[0]))
    snout = (hx + 10.2 * d[0], hy + 10.2 * d[1])
    apex = (hx + 1.2 * d[0], hy + 1.2 * d[1])
    lip1 = (snout[0] + 4.6 * nrm[0] + 1.6 * d[0], snout[1] + 4.6 * nrm[1] + 1.6 * d[1])
    lip2 = (snout[0] - 4.6 * nrm[0] + 1.6 * d[0], snout[1] - 4.6 * nrm[1] + 1.6 * d[1])
    eye = (hx - 2.2 * d[0] + 3.2 * nrm[0], hy - 2.2 * d[1] + 3.2 * nrm[1])
    tail0, tail1 = pt(HEAD - 26), pt(HEAD - 6)
    return "\n".join([
        f'<path d="{body_path()}" fill="{ink}"/>',
        f'<ellipse cx="{hx:.2f}" cy="{hy:.2f}" rx="11" ry="8.4" transform="rotate({turn:.1f} {hx:.2f} {hy:.2f})" fill="{ink}"/>',  # noqa: E501
        f'<path d="M {apex[0]:.1f} {apex[1]:.1f} L {lip1[0]:.1f} {lip1[1]:.1f} L {lip2[0]:.1f} {lip2[1]:.1f} Z" fill="{ground}"/>',  # noqa: E501
        f'<path d="M {tail0[0]:.1f} {tail0[1]:.1f} A {R} {R} 0 0 1 {tail1[0]:.1f} {tail1[1]:.1f}" fill="none" stroke="{ink}" stroke-width="2.6" stroke-linecap="round"/>',  # noqa: E501
        f'<circle cx="{eye[0]:.2f}" cy="{eye[1]:.2f}" r="1.9" fill="{ground}"/>',
        f'<circle cx="{C:.0f}" cy="{C:.0f}" r="8.5" fill="{ink}" opacity="{moon_opacity}"/>',
        f'<circle cx="{C - 3.2:.1f}" cy="{C - 2.6:.1f}" r="2.1" fill="{ground}" opacity="0.45"/>',
        f'<circle cx="{C + 3.4:.1f}" cy="{C + 3.1:.1f}" r="2.5" fill="{ground}" opacity="0.3"/>',
    ])


if __name__ == "__main__":
    print(mark(*(sys.argv[1:3] or ["#38d7ff", "#03070c"])))

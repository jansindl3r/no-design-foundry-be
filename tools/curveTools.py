from fontTools.misc.bezierTools import splitCubicAtT, splitQuadraticAtT

QUADRATIC = "qcurve"
BEZIER = "curve"


class CheckComplexQuadPointPen:

    allowHandleCount = [0, 2]

    def __init__(self):
        self.handleCount = set()

    def beginPath(self, identifier=None):
        self._count = 0

    def addPoint(self, pt, segmentType, *args, **kwargs):
        if segmentType is None:
            self._count += 1
        else:
            if self._count not in self.allowHandleCount:
                self.handleCount.add(self._count)
            self._count = 0

    def endPath(self):
        if self._count not in self.allowHandleCount:
            self.handleCount.add(self._count)

    def addComponent(self, *args, **kwargs):
        pass

    def __bool__(self):
        return bool(self.handleCount)


class CurveConverter(object):

    FACTOR = 1.340   # This guessed value gives amazingly accurate conversion
    FACTORS = {
        QUADRATIC: 1.0 / FACTOR,
        BEZIER:    FACTOR
    }

    bezierType = BEZIER
    quadType = QUADRATIC

    def convertOffCurve(self, on, off, toType):
        onX, onY = on
        offX, offY = off
        factor = self.FACTORS[toType]
        dx = offX - onX
        dy = offY - onY
        x = onX + dx * factor
        y = onY + dy * factor
        return (x, y)

    def convertSegment(self, origin, segment, toType=None):
        if len(segment) == 3:
            onx1, ony1 = self.convertOffCurve(origin, segment[0], toType)
            onx2, ony2 = self.convertOffCurve(segment[2], segment[1], toType)
            return ((onx1, ony1), (onx2, ony2), segment[2])

    def convert(self, glyph, fromType, toType):
        for contour in glyph:
            for index, point in enumerate(contour):
                if point.segmentType == fromType:
                    bcp1 = contour[index - 1]
                    if bcp1.segmentType is None:
                        ox, oy = self.convertOffCurve((point.x, point.y), (bcp1.x, bcp1.y), toType)
                        bcp1.x = ox
                        bcp1.y = oy

                    bcp2 = contour[index - 2]
                    if bcp2.segmentType is None:
                        onCurve = contour[index - 3]
                        ox, oy = self.convertOffCurve((onCurve.x, onCurve.y), (bcp2.x, bcp2.y), toType)
                        bcp2.x = ox
                        bcp2.y = oy

                    point.segmentType = toType

        glyph.dirty = True

    def bezier2quadratic(self, glyph):
        self.convert(glyph, BEZIER, QUADRATIC)

    def quadratic2bezier(self, glyph):
        self.convert(glyph, QUADRATIC, BEZIER)

    def isQuadratic(self, glyph):
        return self.isType(glyph, QUADRATIC)

    def hasComplexQuadratic(self, glyph):
        pen = CheckComplexQuadPointPen()
        glyph.drawPoints(pen)
        return bool(pen)

    def isBezier(self, glyph):
        return self.isType(glyph, BEZIER)

    def isType(self, glyph, isType):
        for contour in glyph:
            foundOnCurve = False
            for point in contour:
                if isType == QUADRATIC and point.segmentType is not None:
                    foundOnCurve = True
                if point.segmentType == isType:
                    return True
            if isType == QUADRATIC and not foundOnCurve:
                return True
        return False

    def toggle(self, glyph):
        if self.isBezier(glyph):
            self.bezier2quadratic(glyph)
        elif self.isQuadratic(glyph):
            self.quadratic2bezier(glyph)


curveConverter = CurveConverter()


class CurveTester(object):

    """
    Requires: _conversionFuzz
    """

    def isCubicCloseToQuad(self, cubic, quad):
        if cubic == quad:
            return True
        cubicPoints = self._cubicTestPoints(*cubic)
        quadraticPoints = self._quadraticTestPoints(*quad)
        xDiffs = 0
        yDiffs = 0
        for i in range(len(cubicPoints)):
            cubic = cubicPoints[i]
            quad = quadraticPoints[i]
            cubicX, cubicY = cubic
            quadX, quadY = quad
            xDiffs += abs(cubicX - quadX)
            yDiffs += abs(cubicY - quadY)
        return xDiffs < self._conversionFuzz and yDiffs < self._conversionFuzz

    def _cubicTestPoints(self, pt1, pt2, pt3, pt4):
        return [
            splitCubicAtT(pt1, pt2, pt3, pt4, 0.25)[0][-1],
            splitCubicAtT(pt1, pt2, pt3, pt4, 0.75)[0][-1]
        ]

    def _quadraticTestPoints(self, pt1, pt2, pt3, pt4):
        mx = pt2[0] + (pt3[0] - pt2[0]) * .5
        my = pt2[1] + (pt3[1] - pt2[1]) * .5
        return [
            splitQuadraticAtT(pt1, pt2, (mx, my), 0.5)[0][-1],
            splitQuadraticAtT((mx, my), pt3, pt4, 0.5)[0][-1]
        ]
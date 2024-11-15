# -*- coding: utf-8 -*-

import numpy
import scipy.signal

from color_modem import qam, comb, utils


class PalVariant(qam.QamConfig):
    def __new__(cls, fsc, bandwidth3db=1300000.0, bandwidth20db=4000000.0):
        return PalVariant.__base__.__new__(cls, fsc, bandwidth3db, bandwidth20db)

    @property
    def frame_cycle(self):
        result = super(PalVariant, self).frame_cycle
        if result % 2 != 0:
            return 2 * result
        else:
            return result


PalVariant.PAL = PalVariant(fsc=4433618.75)
PalVariant.PAL_A = PalVariant(fsc=2660343.75)
PalVariant.PAL_M = PalVariant(fsc=227.25 * 15750.0 * 1000.0 / 1001.0, bandwidth20db=3600000.0)
PalVariant.PAL_N = PalVariant(fsc=3582056.25, bandwidth20db=3600000.0)


class PalSModem(qam.AbstractQamColorModem):
    def __init__(self, line_config, variant=PalVariant.PAL):
        super(PalSModem, self).__init__(line_config, variant)

    @staticmethod
    def encode_components(r, g, b):
        assert len(r) == len(g) == len(b)
        y = 0.299 * r + 0.587 * g + 0.114 * b
        u = -0.147407 * r - 0.289391 * g + 0.436798 * b
        v = 0.614777 * r - 0.514799 * g - 0.099978 * b
        return y, u, v

    @staticmethod
    def decode_components(y, u, v):
        assert len(y) == len(u) == len(v)
        r = y + 1.140250855188141 * v
        g = y - 0.5808092090310976 * v - 0.3939307027516405 * u
        b = y + 2.028397565922921 * u
        return r, g, b

    def modulate_components(self, frame, line, y, u, v):
        start_phase = self.start_phase(frame, line)
        if self.line_config.is_alternate_line(frame, line):
            v = -numpy.array(v, copy=False)
        return self.qam.modulate(start_phase, y, u, v)

    def demodulate_components(self, frame, line, *args, **kwargs):
        start_phase = self.start_phase(frame, line)
        y, u, v = self.qam.demodulate(start_phase, *args, **kwargs)
        if self.line_config.is_alternate_line(frame, line):
            v = -numpy.array(v, copy=False)
        return y, u, v


class PalDModem(comb.AbstractCombModem):
    def __init__(self, line_config, variant=PalVariant.PAL, *args, **kwargs):
        super(PalDModem, self).__init__(PalSModem(line_config, variant), *args, **kwargs)
        self._sin_factor = numpy.sin(0.5 * self.backend.line_shift)
        self._cos_factor = numpy.cos(0.5 * self.backend.line_shift)
        self._filter = utils.iirfilter(6, (
                1.0 - 1300000.0 / self.backend.config.fsc) * self.backend.qam.carrier_phase_step / numpy.pi,
                                       rs=48.0, btype='lowpass', ftype='cheby2')

    def _demodulate_am(self, data, start_phase):
        data2x = scipy.signal.resample_poly(data, up=2, down=1)
        phase = numpy.linspace(start=start_phase, stop=start_phase + len(data2x) * self.backend.qam.carrier_phase_step,
                               num=len(data2x), endpoint=False) % (2.0 * numpy.pi)
        data2x *= numpy.sin(phase)
        data2x = self._filter(data2x)
        return scipy.signal.resample_poly(data2x, up=1, down=2)

    def demodulate_components_combed(self, frame, line, last, curr):
        # PAL-BDGHIK: LS = %pi*1879/1250 ~= %pi*3/2
        # PAL-M:      LS = %pi/2
        # PAL-N:      LS = %pi*629/1250 ~= %pi/2
        #
        # PAL(n) = Y(x) + U(x)*sin(wt(x)+LS*n) - V(x)*cos(wt(x)+LS*n)
        # PAL(n+1) = Y(x) + U(x)*sin(wt(x)+LS*(n+1)) + V(x)*cos(wt(x)+LS*(n+1))
        #
        # PAL(n+1) - PAL(n) = U(x)*(sin(wt(x)+(n+1)*LS) - sin(wt(x)+n*LS)) + V(x)*(cos(wt(x)+(n+1)*LS) + cos(wt(x)+n*LS))
        # PAL(n+1) - PAL(n) = U(x)*2*sin(LS/2)*cos(wt(x) + LS*(n + 1/2)) + V(x)*2*cos(LS/2)*cos(wt(x) + LS*(n + 1/2))
        # PAL(n+1) - PAL(n) = 2*(U(x)*sin(LS/2) + V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 1/2))
        # PAL_BDGHIK(n+1) - PAL_BDGHIK(n) ~= (U(x) - V(x))*sqrt(2)*cos(wt(x) + LS*(n + 1/2))
        # PAL_MN(n+1) - PAL_MN(n) ~= (U(x) + V(x))*sqrt(2)*cos(wt(x) + LS*(n + 1/2))
        #
        # PAL(n+2) - PAL(n+1) = U(x)*(sin(wt(x)+LS*(n+2)) - sin(wt(x)+LS*(n+1))) - V(x)*(cos(wt(x)+LS*(n+2)) + cos(wt(x)+LS*(n+1)))
        # PAL(n+2) - PAL(n+1) = U(x)*2*sin(LS/2)*cos(wt(x) + LS*(n + 3/2)) - V(x)*2*cos(LS/2)*cos(wt(x) + LS*(n + 3/2))
        # PAL(n+2) - PAL(n+1) = 2*(U(x)*sin(LS/2) - V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 3/2))
        # PAL_BDGHIK(n+2) - PAL_BDGHIK(n+1) ~= (U(x) + V(x))*sqrt(2)*cos(wt(x) + LS*(n + 3/2))
        # PAL_MN(n+2) - PAL_MN(n+1) ~= (U(x) - V(x))*sqrt(2)*cos(wt(x) + LS*(n + 3/2))
        #
        # PAL(n+1) + PAL(n) = 2*Y(x) + U(x)*(sin(wt(x)+LS*(n+1)) + sin(wt(x)+LS*n)) + V(x)*(cos(wt(x)+LS*(n+1)) - cos(wt(x)+LS*n))
        # PAL(n+1) + PAL(n) = 2*Y(x) + U(x)*2*cos(LS/2)*sin(wt(x) + LS*(n + 1/2)) - V(x)*2*sin(LS/2)*sin(wt(x) + LS*(n + 1/2))
        # PAL(n+1) + PAL(n) = 2*Y(x) + 2*(U(x)*cos(LS/2) - V(x)*sin(LS/2))*sin(wt(x) + LS*(n + 1/2))
        # PAL_BDGHIK(n+1) + PAL_BDGHIK(n) ~= 2*Y(x) - (U(x) + V(x))*sqrt(2)*sin(wt(x) + LS*(n + 1/2))
        # PAL_MN(n+1) + PAL_MN(n) ~= 2*Y(x) + (U(x) - V(x))*sqrt(2)*sin(wt(x) + LS*(n + 1/2))
        #
        # PAL(n+2) + PAL(n+1) = 2*Y(x) + U(x)*(sin(wt(x)+LS*(n+2)) + sin(wt(x)+LS*(n+1))) - V(x)*(cos(wt(x)+LS*(n+2)) - cos(wt(x)+LS*(n+1)))
        # PAL(n+2) + PAL(n+1) = 2*Y(x) + U(x)*2*cos(LS/2)*sin(wt(x) + LS*(n + 3/2)) + V(x)*2*sin(LS/2)*sin(wt(x) + LS*(n + 3/2))
        # PAL(n+2) + PAL(n+1) = 2*Y(x) + 2*(U(x)*cos(LS/2) + V(x)*sin(LS/2))*sin(wt(x) + LS*(n + 3/2))
        # PAL_BDGHIK(n+2) + PAL_BDGHIK(n+1) ~= 2*Y(x) - (U(x) - V(x))*sqrt(2)*sin(wt(x) + LS*(n + 3/2))
        # PAL_MN(n+2) + PAL_MN(n+1) ~= 2*Y(x) + (U(x) + V(x))*sqrt(2)*sin(wt(x) + LS*(n + 3/2))
        last = numpy.array(last, copy=False)
        curr = numpy.array(curr, copy=False)

        diff_phase = (self.backend.start_phase(frame, line) + self.backend.qam.extract_chroma_phase_shift
                      - 0.5 * self.backend.line_shift) % (2.0 * numpy.pi)

        sumsig = self.backend.qam.extract_chroma(curr + last)
        diff = self.backend.qam.extract_chroma(curr - last)

        sumsig = self._demodulate_am(sumsig, diff_phase)
        diff = self._demodulate_am(diff, (diff_phase + 0.5 * numpy.pi) % (2.0 * numpy.pi))

        u = diff * self._sin_factor + sumsig * self._cos_factor
        v = diff * self._cos_factor - sumsig * self._sin_factor
        if self.backend.line_config.is_alternate_line(frame, line):
            v *= -1.0

        return curr, u, v


class Pal3DModem(PalDModem):
    def __init__(self, *args, **kwargs):  # avg=None
        if 'use_sin' in kwargs:
            use_sin = kwargs['use_sin']
            del kwargs['use_sin']
        else:
            use_sin = True

        if 'use_cos' in kwargs:
            use_cos = kwargs['use_cos']
            del kwargs['use_cos']
        else:
            use_cos = True

        if 'avg' in kwargs:
            avg = kwargs['avg']
            del kwargs['avg']
        else:
            avg = None

        super(Pal3DModem, self).__init__(*args, **kwargs)
        self._last_diff = None
        self._last_demodulated = None
        self.demodulation_delay = 1

        lssin = numpy.sin(self.backend.line_shift)
        if abs(lssin) < 0.1:
            use_sin = False

        lscos = numpy.cos(self.backend.line_shift)
        if abs(lscos) > 0.9:
            use_cos = False

        self.demodulation_delay = 1 if use_cos or use_sin else 0

        self._use_sin = use_sin
        self._use_cos = use_cos

        if use_sin:
            self._sin_sum_factor = 0.5 / lssin

        if use_cos:
            self._cos_u_factor = -0.5 / (1.0 - lscos)
            self._cos_v_factor = -0.5 / (1.0 + lscos)

        if avg is not None:
            self._avg = avg
        else:
            self._avg = comb.avg

    def demodulate_components(self, frame, line, composite, strip_chroma=True, *args, **kwargs):
        if not (self._use_sin or self._use_cos):
            return super(Pal3DModem, self).demodulate_components(frame, line, composite, strip_chroma, *args, **kwargs)

        # (PAL(n+2) - PAL(n+1)) + (PAL(n+1) - PAL(n)) = 2*(U(x)*sin(LS/2) - V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 3/2)) + 2*(U(x)*sin(LS/2) + V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 1/2))
        # (PAL(n+2) - PAL(n+1)) - (PAL(n+1) - PAL(n)) = 2*(U(x)*sin(LS/2) - V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 3/2)) - 2*(U(x)*sin(LS/2) + V(x)*cos(LS/2))*cos(wt(x) + LS*(n + 1/2))
        #
        # (PAL(n+2) - PAL(n+1)) + (PAL(n+1) - PAL(n)) = 2*sin(LS)*(U(x)*cos(wt(x)+(n+1)*LS) + V(x)*sin(wt(x)+(n+1)*LS))
        # (PAL(n+2) - PAL(n+1)) - (PAL(n+1) - PAL(n)) = -2*(U(x)*(1-cos(LS))*sin(wt(x)+(n+1)*LS) + V(x)*(1+cos(LS))*cos(wt(x)+(n+1)*LS))
        composite = numpy.array(composite, copy=False)

        if frame != self._last_frame or line != self._last_line + 2:
            self._last_diff = None
            self._last_demodulated = super(Pal3DModem, self).demodulate_components(frame, line, composite, strip_chroma=False,
                                                                                   *args, **kwargs)
            return self._last_demodulated

        assert self._last_composite is not None
        curr_diff = composite - self._last_composite
        if self._last_diff is None:
            y, u, v = self._last_demodulated
            self._last_demodulated = None
        else:
            sumsig = curr_diff + self._last_diff
            diffsig = curr_diff - self._last_diff

            start_phase = self.backend.start_phase(frame, line - 2)
            sumsig = self.backend.qam.demodulate(start_phase, sumsig, strip_chroma=False)
            diffsig = self.backend.qam.demodulate(start_phase, diffsig, strip_chroma=False)

            if self._use_sin and self._use_cos:
                u = self._avg(sumsig[2] * self._sin_sum_factor, diffsig[1] * self._cos_u_factor)
                v = self._avg(sumsig[1] * self._sin_sum_factor, diffsig[2] * self._cos_v_factor)
            elif self._use_sin:
                u = self._sin_sum_factor * sumsig[2]
                v = self._sin_sum_factor * sumsig[1]
            elif self._use_cos:
                u = self._cos_u_factor * diffsig[1]
                v = self._cos_v_factor * diffsig[2]

            if self.backend.line_config.is_alternate_line(frame, line - 2):
                v *= -1.0

            y = self._last_composite

        if strip_chroma:
            y = y - self.backend.modulate_components(frame, line - 2, numpy.zeros(len(composite)), u, v)
            if self.notch:
                y = self.notch(y)

        self._last_frame = frame
        self._last_line = line
        self._last_composite = numpy.array(composite)
        self._last_diff = curr_diff
        return y, u, v

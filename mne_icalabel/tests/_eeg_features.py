from numpy.typing import ArrayLike
from typing import List, Tuple
import numpy as np
import math
import scipy.signal as ss
from scipy.fft import fft
import warnings

# TODO: remove this file


def eeg_features(
    icaact: np.array,
    trials: int,
    srate: int,
    pnts: int,
    icaweights: np.array,
    icawinv: np.array,
    th: np.array,
    rd: np.array,
    subset: np.array = None,
    pct_data: int = 100,
) -> np.array:
    """
    Generates the feature nd-array for ICLabel.

    Args:
        icaact (np.array): ICA activation waveforms
        trials (int): Number of trials
        srate (int): Sampling Rate
        pnts (int): Number of Points
        icaweights (np.array): ICA Weights
        icawinv (np.array): pinv(EEG.icaweights*EEG.icasphere)
        th (np.array): Theta coordinates of electrodes (polar)
        rd (np.array): Rho coordinates of electrodes (polar)
        pct_data (int, optional): . Defaults to 100.
        subset (np.array): Subset of indices (Randomly generated.
        Can be inputted for testing)

    Returns:
        np.array: Feature matrix (4D)
    """
    # Generate topoplot features
    ncomp = icawinv.shape[1]
    topo = np.zeros((32, 32, 1, ncomp))
    plotchans = np.squeeze(np.argwhere(~np.isnan(np.squeeze(th))))
    for it in range(ncomp):
        temp_topo = eeg_topoplot(
            icawinv=icawinv[:, it : it + 1], Th=th, Rd=rd, plotchans=plotchans
        )
        np.nan_to_num(temp_topo, copy=False)  # Set NaN values to 0 in-place
        topo[:, :, 0, it] = temp_topo / np.max(np.abs(temp_topo))

    # Generate PSD Features
    print("inside original...")
    print(icaact.shape, icaweights.shape, len(icaweights), srate, pnts, subset)
    psd = eeg_rpsd(
        icaact=icaact,
        icaweights=icaweights,
        trials=trials,
        srate=srate,
        pnts=pnts,
        subset=subset,
    )

    # Autocorrelation
    autocorr = eeg_autocorr_fftw(
        icaact=icaact, trials=trials, srate=srate, pnts=pnts, pct_data=pct_data
    )
    autocorr = np.expand_dims(autocorr, (2, 3))
    autocorr = np.transpose(autocorr, [2, 1, 3, 0])

    return [0.99 * topo, 0.99 * psd, 0.99 * autocorr]


def nextpow2(x):
    return math.ceil(math.log2(abs(x)))


def eeg_autocorr_fftw(
    icaact: np.array, trials: int, srate: float, pnts: int, pct_data: int = 100
) -> np.array:
    """
    Generates autocorrelation features for ICLabel.

    Args:
        icaact (np.array): ICA activation waveforms
        trials (int): number of trials
        srate (float): sample rate
        pnts (int): number of points
        pct_data (int, optional): [description]. Defaults to 100.

    Returns:
        np.array: autocorrelation feature
    """
    nfft = 2 ** nextpow2(2 * pnts - 1)
    ac = np.zeros((len(icaact), nfft), dtype=np.float64)

    for it in range(len(icaact)):
        X = np.fft.fft(icaact[it : it + 1, :, :], n=nfft, axis=1)
        ac[it : it + 1, :] = np.mean(np.power(np.abs(X), 2), 2)

    ac = np.real_if_close(np.fft.ifft(ac, n=None, axis=1))  # ifft

    if pnts < srate:
        ac = np.hstack((ac[:, 0:pnts], np.zeros((len(ac), srate - pnts + 1))))
    else:
        ac = ac[:, 0 : srate + 1]

    ac = ac[:, 0 : srate + 1] / ac[:, 0][:, None]

    resamp = ss.resample_poly(ac.T, 100, int(srate)).T

    return resamp[:, 1:]


def eeg_autocorr_welch(
    icaact: np.array, trials: int, srate: float, pnts: int, pct_data: int = 100
) -> np.array:
    ncomp = icaact.shape[0]
    n_points = min(pnts, srate * 3)
    nfft = 2 ** nextpow2(2 * n_points - 1)
    cutoff = math.floor(pnts / n_points) * n_points

    index = np.ceil(
        np.arange(start=0, stop=cutoff - n_points + 1, step=n_points / 2)
    ) + np.arange(0, n_points).reshape(-1, 1)
    index = index.astype(int)

    segments = icaact[:, index, :].reshape(
        (ncomp, index.shape[0], index.shape[1]), order="F"
    )

    ac = np.zeros((ncomp, nfft), dtype=np.float64)
    for it in range(ncomp):
        fftpow = np.mean(
            np.abs(np.fft.fft(segments[it : it + 1, :, :], n=nfft, axis=1)) ** 2, axis=2
        )
        ac[it : it + 1, :] = np.real(np.fft.ifft(fftpow, n=None, axis=1))

    # normalize
    ac = ac[:, 0 : srate + 1] / (
        ac[:, 0:1]
        * (
            np.hstack(
                (np.arange(n_points, n_points - srate, -1), max(1, n_points - srate))
            )
            / n_points
        )
    )

    resamp = ss.resample_poly(ac.T, 100, int(srate)).T

    return resamp[:, 1:]


def eeg_rpsd(
    icaact: np.array,
    icaweights: np.array,
    pnts: int,
    srate: int,
    trials: int,
    pct_data: int = 100,
    subset=None,
) -> np.array:
    """
    Generates RPSD features for ICLabel.

    Args:
        icaact (np.array): [description]
        icaweights (np.array): [description]
        pnts (int): [description]
        srate (int): [description]
        trials (int): [description]
        pct_data (int, optional): [description]. Defaults to 100.
        subset ([type], optional): [description]. Defaults to None.

    Returns:
        np.array: [description]
    """
    # Clean input cutoff freq
    nyquist = math.floor(srate / 2)
    nfreqs = 100
    if nfreqs > nyquist:
        nfreqs = nyquist

    ncomp = len(icaweights)
    n_points = min(pnts, srate)
    window = np.hamming(n_points).reshape(1, -1)[:, :, np.newaxis]

    cutoff = math.floor(pnts / n_points) * n_points
    index = np.ceil(np.arange(0, cutoff - n_points + 1, n_points / 2)).astype(
        np.int64
    ).reshape(1, -1) + np.arange(0, n_points).reshape(-1, 1)

    n_seg = index.shape[1] * trials
    if subset is None:
        subset = np.random.permutation(n_seg)[: math.ceil(n_seg * pct_data / 100)]

    subset = np.squeeze(subset)

    psdmed = np.zeros((ncomp, nfreqs))
    denom = srate * np.sum(np.power(window, 2))

    for it in range(ncomp):
        temp = icaact[it, index, :].reshape(1, index.shape[0], n_seg, order="F")
        temp = temp[:, :, subset] * window
        temp = fft(temp, n_points, 1)

        temp = temp * np.conjugate(temp)

        temp = temp[:, 1 : (nfreqs + 1), :] * 2 / denom

        if nfreqs == nyquist:

            temp[:, -1, :] /= 2
        psdmed[it, :] = 20 * np.real(np.log10(np.median(temp, axis=2)))

    nfreq = psdmed.shape[1]

    if nfreq < 100:
        psdmed = np.concatenate(
            [psdmed, np.tile(psdmed[:, -1:], (1, 100 - nfreq))], axis=1
        )

    for linenoise_ind in [50, 60]:
        linenoise_around = np.array([linenoise_ind - 1, linenoise_ind + 1])
        difference = (
            psdmed[:, linenoise_around] - psdmed[:, linenoise_ind : linenoise_ind + 1]
        )
        notch_ind = np.all(difference > 5, 1)

        if np.any(notch_ind):
            psdmed[notch_ind, linenoise_ind] = np.mean(
                psdmed[notch_ind, linenoise_around], axis=1
            )

    # # Normalize
    psdmed = psdmed / np.max(np.abs(psdmed), axis=1, keepdims=True)

    psdmed = np.expand_dims(psdmed, (2, 3))
    psdmed = np.transpose(psdmed, [2, 1, 3, 0])

    return psdmed


def pol2cart(theta: ArrayLike, rho: ArrayLike) -> Tuple[ArrayLike, ArrayLike]:
    """
    Converts polar coordinates to cartesian coordinates.

    Args:
        theta (np.array): angle
        rho (np.array): magnitude
    """
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)
    return x, y


def mergesimpts(
    data: ArrayLike, tols: List[ArrayLike], mode: str = "average"
) -> ArrayLike:
    """

    Args:
        data (np.array): [description]
        tols (list[np.array, np.array, np.array]): [description]
        mode (str, optional): [description]. Defaults to 'average'.

    Returns:
        np.array: [description]
    """
    data_ = data.copy()[np.argsort(data[:, 0])]
    newdata = []
    tols_ = np.array(tols)
    idxs_ready = []
    point = 0
    for point in range(data_.shape[0]):
        if point in idxs_ready:
            continue
        else:
            similar_pts = np.where(
                np.prod(np.abs(data_ - data_[point]) < tols_, axis=-1)
            )
            similar_pts = np.array(list(set(similar_pts[0].tolist()) - set(idxs_ready)))
            idxs_ready += similar_pts.tolist()
            if mode == "average":
                exemplar = np.mean(data_[similar_pts], axis=0)
            else:
                exemplar = data_[similar_pts].copy()[0]  # first
            newdata.append(exemplar)
    return np.array(newdata)


def mergepoints2D(
    x: ArrayLike, y: ArrayLike, v: ArrayLike
) -> Tuple[ArrayLike, ArrayLike, ArrayLike]:
    """
    Averages values for points that are close to each other.

    Args:
        x (np.array): x-coordinates
        y (np.array): y-coordinates
        v (np.array): values

    Returns:
        tuple[np.array, np.array, np.array]: [description]
    """
    # Sort x and y so duplicate points can be averaged
    # Need x,y and z to be column vectors
    sz = x.size
    x = x.copy()
    y = y.copy()
    v = v.copy()
    x = np.reshape(x, sz, order="F")
    y = np.reshape(y, sz, order="F")
    v = np.reshape(v, sz, order="F")

    myepsx = np.spacing(0.5 * (np.max(x) - np.min(x))) ** (1 / 3)
    myepsy = np.spacing(0.5 * (np.max(y) - np.min(y))) ** (1 / 3)
    # Look for x, y points that are identical (within a tolerance)
    # Average out the values for these points
    if np.all(np.isreal(v)):
        data = np.stack((y, x, v), axis=-1)
        yxv = mergesimpts(data, [myepsy, myepsx, np.inf], "average")
        x = yxv[:, 1]
        y = yxv[:, 0]
        v = yxv[:, 2]
    else:
        # If z is imaginary split out the real and imaginary parts
        data = np.stack((y, x, np.real(v), np.imag(v)), axis=-1)
        yxv = mergesimpts(data, [myepsy, myepsx, np.inf, np.inf], "average")
        x = yxv[:, 1]
        y = yxv[:, 0]
        # Re-combine the real and imaginary parts
        v = yxv[:, 2] + 1j * yxv[:, 3]

    return x, y, v


def gdatav4(
    x: ArrayLike, y: ArrayLike, v: ArrayLike, xq: ArrayLike, yq: ArrayLike
) -> Tuple[ArrayLike, ArrayLike, ArrayLike]:
    """
    GDATAV4 MATLAB 4 GRIDDATA interpolation
    Reference:  David T. Sandwell, Biharmonic spline
    interpolation of GEOS-3 and SEASAT altimeter
    data, Geophysical Research Letters, 2, 139-142,
    1987.  Describes interpolation using value or
    gradient of value in any dimension.

    Args:
        x (np.array): x-coordinates
        y (np.array): y-coordinates
        v (np.array): values
        xq (np.array): x-grid
        yq (np.array): y-grid

    Returns:
        tuple[np.array, np.array, np.array]: tuple of Xi, Yi, Zi
    """
    x, y, v = mergepoints2D(x, y, v)

    xy = x + 1j * y
    xy = np.squeeze(xy)

    # Determine distances between points
    d = np.abs(np.subtract.outer(xy, xy))
    # % Determine weights for interpolation
    g = np.square(d) * (np.log(d) - 1)  # % Green's function.
    # Fixup value of Green's function along diagonal
    np.fill_diagonal(g, 0)
    weights = np.linalg.lstsq(g, v)[0]

    m, n = xq.shape
    vq = np.zeros(xq.shape)

    # Evaluate at requested points (xq,yq).  Loop to save memory.
    for i in range(m):
        for j in range(n):
            d = np.abs(xq[i, j] + 1j * yq[i, j] - xy)
            g = np.square(d) * (np.log(d) - 1)
            # Value of Green's function at zero
            g[np.where(np.isclose(d, 0))] = 0
            vq[i, j] = (np.expand_dims(g, axis=0) @ np.expand_dims(weights, axis=1))[0][
                0
            ]
    return xq, yq, vq


def eeg_topoplot(
    icawinv: np.array, Th: np.array, Rd: np.array, plotchans: np.array = None
) -> np.array_equal:
    """
    Generates topoplot image for ICLabel

    Args:
        icawinv (np.array): pinv(EEG.icaweights*EEG.icasphere);
        Th (np.array): Theta coordinates of electrodes (polar)
        Rd (np.array): Rho coordinates of electrodes (polar)
        plotchans (np.array): plot channels

    Returns:
        np.array_equal: Heatmap values (32 x 32 image)
    """
    GRID_SCALE = 32
    RMAX = 0.5

    Th = Th * np.pi / 180
    # allchansind = np.array(list(range(Th.shape[1])))
    intchans = np.arange(0, len(plotchans))
    x, y = pol2cart(Th, Rd)
    # allchansind = allchansind[plotchans]

    Rd = Rd[:, plotchans]
    x = x[:, plotchans]
    y = y[:, plotchans]

    intx = x[:, intchans]
    inty = y[:, intchans]
    icawinv = icawinv[plotchans]
    intValues = icawinv[intchans]

    plotrad = min(1.0, np.max(Rd) * 1.02)

    # Squeeze channel locations to <= RMAX
    squeezefac = RMAX / plotrad
    inty *= squeezefac
    intx *= squeezefac

    xi = np.linspace(-0.5, 0.5, GRID_SCALE)
    yi = np.linspace(-0.5, 0.5, GRID_SCALE)

    XQ, YQ = np.meshgrid(xi, yi)

    # Do interpolation with v4 scheme from MATLAB
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        Xi, Yi, Zi = gdatav4(inty, intx, intValues, YQ, XQ)

    mask = np.sqrt(np.power(Xi, 2) + np.power(Yi, 2)) > RMAX
    Zi[mask] = np.nan

    return Zi.T

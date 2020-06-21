import numpy as np


def any_none(*args):
    return any(_ is None for _ in args)


def atleast_2d(data):
    if data.ndim == 1:
        return data.reshape((-1, 1))
    return data


def gi(data):
    out = (np.isnan(atleast_2d(data)).sum(1) == 0).ravel()
    return out if len(out) != 0 else None


def normalizedata(data, scaling):
    # Normalize data to 0 mean, 1 std_deviation, optionally scale data
    mean = np.mean(data, axis=0)
    std_deviation = np.std(data, axis=0)
    data = (data - mean) / (std_deviation * scaling)
    return data


def centerdata(data, scaling):
    # Center data to 0 mean
    mean = np.mean(data, axis=0)
    data = (data - mean) / scaling
    return data


def getdatasize(data):
    if isinstance(data, np.ma.masked_array):
        return data.shape[0] - data.mask.reshape((data.shape[0], -1))[:, 0].sum()
    elif isinstance(data, np.ndarray):
        if len(data) == 0:
            return 0
        return data[gi(data)].shape[0]
    elif isinstance(data, list):
        return sum(getdatasize(d) for d in data)
    else:
        # handle unboxed case for convenience
        assert isinstance(data, int) or isinstance(data, float)
        return 1


def getdatadim(data):
    if isinstance(data, np.ndarray):
        assert data.ndim > 1
        return data.shape[1]
    elif isinstance(data, list):
        assert len(data) > 0
        return getdatadim(data[0])
    else:
        # handle unboxed case for convenience
        assert isinstance(data, int) or isinstance(data, float)
    return 1


def combinedata(datas):
    ret = []
    for data in datas:
        if isinstance(data, np.ma.masked_array):
            ret.append(np.ma.compress_rows(data))
        if isinstance(data, np.ndarray):
            ret.append(data)
        elif isinstance(data, list):
            ret.extend(combinedata(data))
        else:
            # handle unboxed case for convenience
            assert isinstance(data, int) or isinstance(data, float)
            ret.append(np.atleast_1d(data))
    return ret


def flattendata(data):
    # data is either an array (possibly a maskedarray) or a list of arrays
    if isinstance(data, np.ndarray):
        return data
    elif isinstance(data, list) or isinstance(data, tuple):
        if any(isinstance(d, np.ma.MaskedArray) for d in data):
            return np.concatenate([np.ma.compress_rows(d) for d in data])
        else:
            return np.concatenate(data)
    else:
        # handle unboxed case for convenience
        assert isinstance(data, int) or isinstance(data, float)
        return np.atleast_1d(data)


def cumsum(v, strict=False):
    if not strict:
        return np.cumsum(v, axis=0)
    else:
        out = np.zeros_like(v)
        out[1:] = np.cumsum(v[:-1], axis=0)
    return out
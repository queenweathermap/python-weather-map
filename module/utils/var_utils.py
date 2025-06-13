def get_var(ds, var):
    return np.asarray(ds[var]) if var in ds else None

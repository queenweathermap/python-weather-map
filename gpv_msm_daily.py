#!/usr/bin/env python
# coding: utf-8

# # GPV天気図（MSM用）

# In[1]:


import numpy as np
import xarray as xr
from pathlib import Path
from module.gpv_panel_daily_msm import make_daily_weather_panel_multi_time

ncfile = Path("~/gpv_project/data/Z__C_RJTD_20240701000000_MSM_GPV_Rjp_L-pall_FH00-15_grib2.bin.nc").expanduser()
ds = xr.open_dataset(ncfile)

init = np.datetime64("2024-07-01T00:00:00")
times = [init + np.timedelta64(i * 6, 'h') for i in range(4)]
save_path = Path("~/Desktop/msm_weather_map.jpg").expanduser()
make_daily_weather_panel_multi_time(ds, times, save_path)


# In[ ]:





Y=pd.read_csv(args[0])
pairs=[('F5_BOX','F5_BOX_HTF'),('F5_BOX','F5_BOX_RSI'),('F11_RAID','F13_RAID_PD'),('F11_RAID','F11_TSOUP'),('F17_Z','F17_Z_HL'),('F12_MSS','F12_MSS_DISP'),('F9_FVG','F13_FVG_PD'),('F9_FVG','F10_M2022'),('F10_OTE','F16_FIB618'),('F7_RF_TRIPLE','F7_RF_ONLY'),('F1_RSI_DIV','F1_MOM_DIV'),('F1_RSI_DIV','F1_PVT_DIV'),('F9_FVG','F9_IFVG'),('F9_OB','F9_BREAKER'),('F3_BOS','F12_MSS'),('F6_VWAP_CROSS','F6_VWAP_FAIL')]
for tf in ['15m','30m']:
    y=Y[Y.tf==tf]
    for a,b in pairs:
        for ex in ['X5_TRAIL2','X2_SL15_TP3']:
            ra=y[(y.entry==a)&(y.exit==ex)].iloc[0]; rb=y[(y.entry==b)&(y.exit==ex)].iloc[0]
            print(tf,ex[:2],f"{a:13s} n12={ra.n12:6.0f} m12={ra.mean12_pct:+.3f} pre={ra.pre_mean_pct:+.3f} g_is={ra.is_gross_mean_pct:+.3f} | {b:13s} n12={rb.n12:6.0f} m12={rb.mean12_pct:+.3f} pre={rb.pre_mean_pct:+.3f} g_is={rb.is_gross_mean_pct:+.3f}")

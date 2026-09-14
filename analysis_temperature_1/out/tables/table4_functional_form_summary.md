| model | condition | segment | target | n | loso_mse | best_null_loso | bic | best_null_bic | range_ok | zhu_beats_nulls_oos | zhu_beats_nulls_bic | n_over_k_gt_50 | retain_zhu | loso_winner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-4o-mini | base | full | y_raw | 1200 | 0.1486 | 0.1504 | -2260 | -2262 | True | True | False | True | True | zhu |
| gpt-4o-mini | base | full | y_adj | 1200 | 0.1483 | 0.1502 | -2262 | -2264 |  | True | False | True | True | zhu |
| gpt-4o-mini | base | post | y_raw | 920 | 0.1534 | 0.1506 | -1710 | -1733 | True | False | False | True | False | linear |
| gpt-4o-mini | base | post | y_adj | 920 | 0.1529 | 0.1504 | -1711 | -1734 |  | False | False | True | False | linear |
| gpt-4o-mini | placebo | full | y_raw | 878 | 0.1409 | 0.1412 | -1690 | -1697 | True | True | False | True | True | zhu |
| gpt-4o-mini | placebo | full | y_adj | 878 | 0.1399 | 0.1402 | -1695 | -1703 |  | True | False | True | True | zhu |
| gpt-4o-mini | placebo | post | y_raw | 598 | 0.1596 | 0.1566 | -1077 | -1103 | True | False | False | True | False | linear |
| gpt-4o-mini | placebo | post | y_adj | 598 | 0.159 | 0.1555 | -1081 | -1107 |  | False | False | True | False | linear |
| gpt-4o-mini | switch | full | y_raw | 869 | 0.1851 | 0.1856 | -1446 | -1454 | True | True | False | True | True | zhu |
| gpt-4o-mini | switch | full | y_adj | 869 | 0.1842 | 0.1846 | -1450 | -1458 |  | True | False | True | True | zhu |
| gpt-4o-mini | switch | post | y_raw | 589 | 0.1808 | 0.1777 | -989.3 | -1015 | True | False | False | True | False | constant |
| gpt-4o-mini | switch | post | y_adj | 589 | 0.1792 | 0.1767 | -993.5 | -1018 |  | False | False | True | False | constant |
| llama-3.3-70b | base | full | y_raw | 1174 | 0.03002 | 0.04097 | -4101 | -3727 | False | True | True | True | False | zhu |
| llama-3.3-70b | base | full | y_adj | 1174 | 0.01163 | 0.01201 | -5197 | -5174 |  | True | True | True | True | zhu |
| llama-3.3-70b | base | post | y_raw | 896 | 0.0348 | 0.04103 | -2992 | -2850 | True | True | True | True | True | zhu |
| llama-3.3-70b | base | post | y_adj | 896 | 0.01194 | 0.01188 | -3940 | -3966 |  | False | False | True | False | spline |
| llama-3.3-70b | placebo | full | y_raw | 969 | 0.03614 | 0.04783 | -3208 | -2920 | True | True | True | True | True | zhu |
| llama-3.3-70b | placebo | full | y_adj | 969 | 0.01105 | 0.0114 | -4332 | -4314 |  | True | True | True | True | zhu |
| llama-3.3-70b | placebo | post | y_raw | 710 | 0.04181 | 0.04973 | -2244 | -2119 | True | True | True | True | True | zhu |
| llama-3.3-70b | placebo | post | y_adj | 710 | 0.01125 | 0.01156 | -3163 | -3159 |  | True | True | True | True | zhu |
| llama-3.3-70b | switch | full | y_raw | 834 | 0.03109 | 0.04315 | -2883 | -2599 | False | True | True | True | False | zhu |
| llama-3.3-70b | switch | full | y_adj | 834 | 0.012 | 0.01235 | -3661 | -3648 |  | True | True | True | True | zhu |
| llama-3.3-70b | switch | post | y_raw | 560 | 0.03908 | 0.04669 | -1802 | -1705 | True | True | True | True | True | zhu |
| llama-3.3-70b | switch | post | y_adj | 560 | 0.01335 | 0.01317 | -2404 | -2420 |  | False | False | True | False | log |
| qwen3-235b | base | full | y_raw | 1135 | 0.02761 | 0.02761 | -4062 | -4069 | True | False | False | True | False | spline |
| qwen3-235b | base | full | y_adj | 1135 | 0.02756 | 0.02723 | -4079 | -4085 |  | False | False | True | False | spline |
| qwen3-235b | base | post | y_raw | 858 | 0.02504 | 0.02496 | -3150 | -3163 | True | False | False | True | False | spline |
| qwen3-235b | base | post | y_adj | 858 | 0.02496 | 0.02489 | -3152 | -3167 |  | False | False | True | False | spline |
| qwen3-235b | placebo | full | y_raw | 544 | 0.04526 | 0.04538 | -1657 | -1667 | True | True | False | True | True | zhu |
| qwen3-235b | placebo | full | y_adj | 544 | 0.03842 | 0.04071 | -1747 | -1733 |  | True | True | True | True | zhu |
| qwen3-235b | placebo | post | y_raw | 266 | 0.05568 | 0.05578 | -744.8 | -764.8 | True | True | False | False | False | zhu |
| qwen3-235b | placebo | post | y_adj | 266 | 0.04349 | 0.04194 | -818.5 | -841 |  | False | False | False | False | constant |
| qwen3-235b | switch | full | y_raw | 549 | 0.05078 | 0.0511 | -1614 | -1614 | True | True | True | True | True | zhu |
| qwen3-235b | switch | full | y_adj | 549 | 0.04075 | 0.04164 | -1731 | -1730 |  | True | True | True | True | zhu |
| qwen3-235b | switch | post | y_raw | 275 | 0.04953 | 0.04831 | -808.4 | -830.4 | True | False | False | False | False | constant |
| qwen3-235b | switch | post | y_adj | 275 | 0.03851 | 0.03777 | -878.1 | -897.9 |  | False | False | False | False | linear |

| model | condition | segment | target | candidate | k | n | rss | aic | bic | loso_mse | range_ok |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-4o-mini | base | full | y_raw | constant | 1 | 1200 | 181.2 | -2267 | -2262 | 0.1512 | True |
| gpt-4o-mini | base | full | y_raw | linear | 2 | 1200 | 181.1 | -2265 | -2255 | 0.1514 | True |
| gpt-4o-mini | base | full | y_raw | log | 2 | 1200 | 181.1 | -2266 | -2255 | 0.1513 | True |
| gpt-4o-mini | base | full | y_raw | spline | 4 | 1200 | 179.6 | -2271 | -2251 | 0.1504 | True |
| gpt-4o-mini | base | full | y_raw | zhu | 6 | 1200 | 176.1 | -2291 | -2260 | 0.1486 | True |
| gpt-4o-mini | base | full | y_adj | constant | 1 | 1200 | 180.9 | -2269 | -2264 | 0.151 |  |
| gpt-4o-mini | base | full | y_adj | linear | 2 | 1200 | 180.8 | -2267 | -2257 | 0.1511 |  |
| gpt-4o-mini | base | full | y_adj | log | 2 | 1200 | 180.8 | -2267 | -2257 | 0.1511 |  |
| gpt-4o-mini | base | full | y_adj | spline | 4 | 1200 | 179.3 | -2273 | -2253 | 0.1502 |  |
| gpt-4o-mini | base | full | y_adj | zhu | 6 | 1200 | 175.8 | -2293 | -2262 | 0.1483 |  |
| gpt-4o-mini | base | post | y_raw | constant | 1 | 920 | 138.8 | -1738 | -1733 | 0.1512 | True |
| gpt-4o-mini | base | post | y_raw | linear | 2 | 920 | 137.9 | -1742 | -1732 | 0.1506 | True |
| gpt-4o-mini | base | post | y_raw | log | 2 | 920 | 137.9 | -1742 | -1733 | 0.1507 | True |
| gpt-4o-mini | base | post | y_raw | spline | 4 | 920 | 137.6 | -1740 | -1721 | 0.1509 | True |
| gpt-4o-mini | base | post | y_raw | zhu | 6 | 920 | 137.2 | -1739 | -1710 | 0.1534 | True |
| gpt-4o-mini | base | post | y_adj | constant | 1 | 920 | 138.7 | -1739 | -1734 | 0.1511 |  |
| gpt-4o-mini | base | post | y_adj | linear | 2 | 920 | 137.7 | -1744 | -1734 | 0.1504 |  |
| gpt-4o-mini | base | post | y_adj | log | 2 | 920 | 137.6 | -1744 | -1734 | 0.1504 |  |
| gpt-4o-mini | base | post | y_adj | spline | 4 | 920 | 137.4 | -1742 | -1722 | 0.1507 |  |
| gpt-4o-mini | base | post | y_adj | zhu | 6 | 920 | 136.9 | -1740 | -1711 | 0.1529 |  |
| gpt-4o-mini | placebo | full | y_raw | constant | 1 | 878 | 126.2 | -1701 | -1697 | 0.144 | True |
| gpt-4o-mini | placebo | full | y_raw | linear | 2 | 878 | 126.1 | -1700 | -1690 | 0.1441 | True |
| gpt-4o-mini | placebo | full | y_raw | log | 2 | 878 | 125.5 | -1704 | -1694 | 0.1434 | True |
| gpt-4o-mini | placebo | full | y_raw | spline | 4 | 878 | 123.2 | -1716 | -1697 | 0.1412 | True |
| gpt-4o-mini | placebo | full | y_raw | zhu | 6 | 878 | 122.3 | -1718 | -1690 | 0.1409 | True |
| gpt-4o-mini | placebo | full | y_adj | constant | 1 | 878 | 125.5 | -1706 | -1701 | 0.1433 |  |
| gpt-4o-mini | placebo | full | y_adj | linear | 2 | 878 | 125.5 | -1704 | -1695 | 0.1434 |  |
| gpt-4o-mini | placebo | full | y_adj | log | 2 | 878 | 124.8 | -1709 | -1700 | 0.1426 |  |
| gpt-4o-mini | placebo | full | y_adj | spline | 4 | 878 | 122.4 | -1722 | -1703 | 0.1402 |  |
| gpt-4o-mini | placebo | full | y_adj | zhu | 6 | 878 | 121.6 | -1723 | -1695 | 0.1399 |  |
| gpt-4o-mini | placebo | post | y_raw | constant | 1 | 598 | 93.53 | -1107 | -1103 | 0.157 | True |
| gpt-4o-mini | placebo | post | y_raw | linear | 2 | 598 | 93.12 | -1108 | -1099 | 0.1566 | True |
| gpt-4o-mini | placebo | post | y_raw | log | 2 | 598 | 93.19 | -1108 | -1099 | 0.1567 | True |
| gpt-4o-mini | placebo | post | y_raw | spline | 4 | 598 | 92.92 | -1105 | -1088 | 0.1569 | True |
| gpt-4o-mini | placebo | post | y_raw | zhu | 6 | 598 | 92.62 | -1103 | -1077 | 0.1596 | True |
| gpt-4o-mini | placebo | post | y_adj | constant | 1 | 598 | 92.97 | -1111 | -1107 | 0.1561 |  |
| gpt-4o-mini | placebo | post | y_adj | linear | 2 | 598 | 92.51 | -1112 | -1103 | 0.1555 |  |
| gpt-4o-mini | placebo | post | y_adj | log | 2 | 598 | 92.6 | -1111 | -1103 | 0.1557 |  |
| gpt-4o-mini | placebo | post | y_adj | spline | 4 | 598 | 92.27 | -1110 | -1092 | 0.1558 |  |
| gpt-4o-mini | placebo | post | y_adj | zhu | 6 | 598 | 91.94 | -1108 | -1081 | 0.159 |  |
| gpt-4o-mini | switch | full | y_raw | constant | 1 | 869 | 161.8 | -1459 | -1454 | 0.1869 | True |
| gpt-4o-mini | switch | full | y_raw | linear | 2 | 869 | 161.8 | -1457 | -1447 | 0.1874 | True |
| gpt-4o-mini | switch | full | y_raw | log | 2 | 869 | 161.2 | -1460 | -1450 | 0.1867 | True |
| gpt-4o-mini | switch | full | y_raw | spline | 4 | 869 | 159.6 | -1465 | -1446 | 0.1856 | True |
| gpt-4o-mini | switch | full | y_raw | zhu | 6 | 869 | 157.1 | -1475 | -1446 | 0.1851 | True |
| gpt-4o-mini | switch | full | y_adj | constant | 1 | 869 | 161.1 | -1463 | -1458 | 0.1861 |  |
| gpt-4o-mini | switch | full | y_adj | linear | 2 | 869 | 161 | -1461 | -1451 | 0.1865 |  |
| gpt-4o-mini | switch | full | y_adj | log | 2 | 869 | 160.4 | -1464 | -1455 | 0.1857 |  |
| gpt-4o-mini | switch | full | y_adj | spline | 4 | 869 | 158.8 | -1469 | -1450 | 0.1846 |  |
| gpt-4o-mini | switch | full | y_adj | zhu | 6 | 869 | 156.3 | -1479 | -1450 | 0.1842 |  |
| gpt-4o-mini | switch | post | y_raw | constant | 1 | 589 | 104 | -1019 | -1015 | 0.1777 | True |
| gpt-4o-mini | switch | post | y_raw | linear | 2 | 589 | 103.9 | -1018 | -1009 | 0.1781 | True |
| gpt-4o-mini | switch | post | y_raw | log | 2 | 589 | 103.9 | -1018 | -1009 | 0.1783 | True |
| gpt-4o-mini | switch | post | y_raw | spline | 4 | 589 | 103.4 | -1016 | -999 | 0.1782 | True |
| gpt-4o-mini | switch | post | y_raw | zhu | 6 | 589 | 102.9 | -1016 | -989.3 | 0.1808 | True |
| gpt-4o-mini | switch | post | y_adj | constant | 1 | 589 | 103.4 | -1023 | -1018 | 0.1767 |  |
| gpt-4o-mini | switch | post | y_adj | linear | 2 | 589 | 103.3 | -1021 | -1013 | 0.177 |  |
| gpt-4o-mini | switch | post | y_adj | log | 2 | 589 | 103.3 | -1021 | -1012 | 0.1772 |  |
| gpt-4o-mini | switch | post | y_adj | spline | 4 | 589 | 102.8 | -1020 | -1002 | 0.1771 |  |
| gpt-4o-mini | switch | post | y_adj | zhu | 6 | 589 | 102.2 | -1020 | -993.5 | 0.1792 |  |
| llama-3.3-70b | base | full | y_raw | constant | 1 | 1174 | 48.78 | -3732 | -3727 | 0.04162 | True |
| llama-3.3-70b | base | full | y_raw | linear | 2 | 1174 | 48.78 | -3730 | -3720 | 0.04165 | True |
| llama-3.3-70b | base | full | y_raw | log | 2 | 1174 | 48.73 | -3732 | -3721 | 0.0416 | True |
| llama-3.3-70b | base | full | y_raw | spline | 4 | 1174 | 47.92 | -3747 | -3727 | 0.04097 | True |
| llama-3.3-70b | base | full | y_raw | zhu | 6 | 1174 | 34.44 | -4131 | -4101 | 0.03002 | False |
| llama-3.3-70b | base | full | y_adj | constant | 1 | 1174 | 14.25 | -5177 | -5172 | 0.01219 |  |
| llama-3.3-70b | base | full | y_adj | linear | 2 | 1174 | 14.25 | -5175 | -5165 | 0.01221 |  |
| llama-3.3-70b | base | full | y_adj | log | 2 | 1174 | 14.25 | -5175 | -5165 | 0.0122 |  |
| llama-3.3-70b | base | full | y_adj | spline | 4 | 1174 | 13.97 | -5194 | -5174 | 0.01201 |  |
| llama-3.3-70b | base | full | y_adj | zhu | 6 | 1174 | 13.54 | -5227 | -5197 | 0.01163 |  |
| llama-3.3-70b | base | post | y_raw | constant | 1 | 896 | 36.96 | -2854 | -2850 | 0.04135 | True |
| llama-3.3-70b | base | post | y_raw | linear | 2 | 896 | 36.79 | -2857 | -2847 | 0.0412 | True |
| llama-3.3-70b | base | post | y_raw | log | 2 | 896 | 36.73 | -2858 | -2849 | 0.04113 | True |
| llama-3.3-70b | base | post | y_raw | spline | 4 | 896 | 36.58 | -2858 | -2839 | 0.04103 | True |
| llama-3.3-70b | base | post | y_raw | zhu | 6 | 896 | 30.37 | -3020 | -2992 | 0.0348 | True |
| llama-3.3-70b | base | post | y_adj | constant | 1 | 896 | 10.63 | -3971 | -3966 | 0.01193 |  |
| llama-3.3-70b | base | post | y_adj | linear | 2 | 896 | 10.62 | -3970 | -3960 | 0.01195 |  |
| llama-3.3-70b | base | post | y_adj | log | 2 | 896 | 10.62 | -3970 | -3961 | 0.01195 |  |
| llama-3.3-70b | base | post | y_adj | spline | 4 | 896 | 10.52 | -3975 | -3955 | 0.01188 |  |
| llama-3.3-70b | base | post | y_adj | zhu | 6 | 896 | 10.53 | -3969 | -3940 | 0.01194 |  |
| llama-3.3-70b | placebo | full | y_raw | constant | 1 | 969 | 47.61 | -2918 | -2913 | 0.04917 | True |
| llama-3.3-70b | placebo | full | y_raw | linear | 2 | 969 | 47.61 | -2916 | -2906 | 0.04919 | True |
| llama-3.3-70b | placebo | full | y_raw | log | 2 | 969 | 47.42 | -2920 | -2910 | 0.04898 | True |
| llama-3.3-70b | placebo | full | y_raw | spline | 4 | 969 | 46.25 | -2940 | -2920 | 0.04783 | True |
| llama-3.3-70b | placebo | full | y_raw | zhu | 6 | 969 | 33.9 | -3237 | -3208 | 0.03614 | True |
| llama-3.3-70b | placebo | full | y_adj | constant | 1 | 969 | 11.67 | -4280 | -4275 | 0.01206 |  |
| llama-3.3-70b | placebo | full | y_adj | linear | 2 | 969 | 11.62 | -4283 | -4273 | 0.01202 |  |
| llama-3.3-70b | placebo | full | y_adj | log | 2 | 969 | 11.67 | -4278 | -4269 | 0.01207 |  |
| llama-3.3-70b | placebo | full | y_adj | spline | 4 | 969 | 10.98 | -4333 | -4314 | 0.0114 |  |
| llama-3.3-70b | placebo | full | y_adj | zhu | 6 | 969 | 10.62 | -4361 | -4332 | 0.01105 |  |
| llama-3.3-70b | placebo | post | y_raw | constant | 1 | 710 | 35.83 | -2118 | -2114 | 0.05052 | True |
| llama-3.3-70b | placebo | post | y_raw | linear | 2 | 710 | 35.25 | -2128 | -2119 | 0.04976 | True |
| llama-3.3-70b | placebo | post | y_raw | log | 2 | 710 | 35.22 | -2129 | -2119 | 0.04973 | True |
| llama-3.3-70b | placebo | post | y_raw | spline | 4 | 710 | 35.19 | -2125 | -2107 | 0.04976 | True |
| llama-3.3-70b | placebo | post | y_raw | zhu | 6 | 710 | 28.46 | -2272 | -2244 | 0.04181 | True |
| llama-3.3-70b | placebo | post | y_adj | constant | 1 | 710 | 8.54 | -3137 | -3132 | 0.01206 |  |
| llama-3.3-70b | placebo | post | y_adj | linear | 2 | 710 | 8.156 | -3167 | -3158 | 0.01157 |  |
| llama-3.3-70b | placebo | post | y_adj | log | 2 | 710 | 8.151 | -3168 | -3159 | 0.01156 |  |
| llama-3.3-70b | placebo | post | y_adj | spline | 4 | 710 | 8.145 | -3164 | -3146 | 0.01161 |  |
| llama-3.3-70b | placebo | post | y_adj | zhu | 6 | 710 | 7.808 | -3190 | -3163 | 0.01125 |  |
| llama-3.3-70b | switch | full | y_raw | constant | 1 | 834 | 37.06 | -2595 | -2590 | 0.04456 | True |
| llama-3.3-70b | switch | full | y_raw | linear | 2 | 834 | 37.03 | -2593 | -2584 | 0.04459 | True |
| llama-3.3-70b | switch | full | y_raw | log | 2 | 834 | 36.8 | -2599 | -2589 | 0.04428 | True |
| llama-3.3-70b | switch | full | y_raw | spline | 4 | 834 | 35.78 | -2618 | -2599 | 0.04315 | True |
| llama-3.3-70b | switch | full | y_raw | zhu | 6 | 834 | 25.05 | -2911 | -2883 | 0.03109 | False |
| llama-3.3-70b | switch | full | y_adj | constant | 1 | 834 | 10.6 | -3639 | -3634 | 0.01279 |  |
| llama-3.3-70b | switch | full | y_adj | linear | 2 | 834 | 10.59 | -3637 | -3628 | 0.01283 |  |
| llama-3.3-70b | switch | full | y_adj | log | 2 | 834 | 10.57 | -3639 | -3629 | 0.01279 |  |
| llama-3.3-70b | switch | full | y_adj | spline | 4 | 834 | 10.17 | -3667 | -3648 | 0.01235 |  |
| llama-3.3-70b | switch | full | y_adj | zhu | 6 | 834 | 9.855 | -3689 | -3661 | 0.012 |  |
| llama-3.3-70b | switch | post | y_raw | constant | 1 | 560 | 26.52 | -1706 | -1702 | 0.04752 | True |
| llama-3.3-70b | switch | post | y_raw | linear | 2 | 560 | 26.16 | -1712 | -1703 | 0.047 | True |
| llama-3.3-70b | switch | post | y_raw | log | 2 | 560 | 26.05 | -1714 | -1705 | 0.04681 | True |
| llama-3.3-70b | switch | post | y_raw | spline | 4 | 560 | 25.9 | -1713 | -1696 | 0.04669 | True |
| llama-3.3-70b | switch | post | y_raw | zhu | 6 | 560 | 20.95 | -1828 | -1802 | 0.03908 | True |
| llama-3.3-70b | switch | post | y_adj | constant | 1 | 560 | 7.505 | -2413 | -2409 | 0.01351 |  |
| llama-3.3-70b | switch | post | y_adj | linear | 2 | 560 | 7.304 | -2426 | -2417 | 0.01322 |  |
| llama-3.3-70b | switch | post | y_adj | log | 2 | 560 | 7.276 | -2428 | -2420 | 0.01317 |  |
| llama-3.3-70b | switch | post | y_adj | spline | 4 | 560 | 7.256 | -2426 | -2409 | 0.01322 |  |
| llama-3.3-70b | switch | post | y_adj | zhu | 6 | 560 | 7.154 | -2430 | -2404 | 0.01335 |  |
| qwen3-235b | base | full | y_raw | constant | 1 | 1135 | 32.59 | -4028 | -4023 | 0.029 | True |
| qwen3-235b | base | full | y_raw | linear | 2 | 1135 | 32.46 | -4030 | -4020 | 0.02908 | True |
| qwen3-235b | base | full | y_raw | log | 2 | 1135 | 32.13 | -4042 | -4032 | 0.02875 | True |
| qwen3-235b | base | full | y_raw | spline | 4 | 1135 | 30.72 | -4089 | -4069 | 0.02761 | True |
| qwen3-235b | base | full | y_raw | zhu | 6 | 1135 | 30.52 | -4092 | -4062 | 0.02761 | True |
| qwen3-235b | base | full | y_adj | constant | 1 | 1135 | 30.84 | -4090 | -4085 | 0.02744 |  |
| qwen3-235b | base | full | y_adj | linear | 2 | 1135 | 30.8 | -4090 | -4080 | 0.0276 |  |
| qwen3-235b | base | full | y_adj | log | 2 | 1135 | 30.83 | -4089 | -4079 | 0.0276 |  |
| qwen3-235b | base | full | y_adj | spline | 4 | 1135 | 30.3 | -4104 | -4084 | 0.02723 |  |
| qwen3-235b | base | full | y_adj | zhu | 6 | 1135 | 30.07 | -4109 | -4079 | 0.02756 |  |
| qwen3-235b | base | post | y_raw | constant | 1 | 858 | 21.33 | -3168 | -3163 | 0.02527 | True |
| qwen3-235b | base | post | y_raw | linear | 2 | 858 | 21.26 | -3169 | -3159 | 0.02532 | True |
| qwen3-235b | base | post | y_raw | log | 2 | 858 | 21.2 | -3171 | -3162 | 0.02526 | True |
| qwen3-235b | base | post | y_raw | spline | 4 | 858 | 20.86 | -3181 | -3162 | 0.02496 | True |
| qwen3-235b | base | post | y_raw | zhu | 6 | 858 | 20.83 | -3178 | -3150 | 0.02504 | True |
| qwen3-235b | base | post | y_adj | constant | 1 | 858 | 21.24 | -3171 | -3167 | 0.02516 |  |
| qwen3-235b | base | post | y_adj | linear | 2 | 858 | 21.15 | -3173 | -3163 | 0.02518 |  |
| qwen3-235b | base | post | y_adj | log | 2 | 858 | 21.1 | -3175 | -3166 | 0.02512 |  |
| qwen3-235b | base | post | y_adj | spline | 4 | 858 | 20.82 | -3183 | -3164 | 0.02489 |  |
| qwen3-235b | base | post | y_adj | zhu | 6 | 858 | 20.77 | -3181 | -3152 | 0.02496 |  |
| qwen3-235b | placebo | full | y_raw | constant | 1 | 544 | 26.68 | -1638 | -1634 | 0.04928 | True |
| qwen3-235b | placebo | full | y_raw | linear | 2 | 544 | 26.07 | -1649 | -1640 | 0.04836 | True |
| qwen3-235b | placebo | full | y_raw | log | 2 | 544 | 25.32 | -1665 | -1656 | 0.04689 | True |
| qwen3-235b | placebo | full | y_raw | spline | 4 | 544 | 24.26 | -1684 | -1667 | 0.04538 | True |
| qwen3-235b | placebo | full | y_raw | zhu | 6 | 544 | 24.11 | -1683 | -1657 | 0.04526 | True |
| qwen3-235b | placebo | full | y_adj | constant | 1 | 544 | 22.81 | -1723 | -1719 | 0.04211 |  |
| qwen3-235b | placebo | full | y_adj | linear | 2 | 544 | 22.19 | -1736 | -1728 | 0.04118 |  |
| qwen3-235b | placebo | full | y_adj | log | 2 | 544 | 21.97 | -1742 | -1733 | 0.04071 |  |
| qwen3-235b | placebo | full | y_adj | spline | 4 | 544 | 21.77 | -1743 | -1726 | 0.04076 |  |
| qwen3-235b | placebo | full | y_adj | zhu | 6 | 544 | 20.47 | -1772 | -1747 | 0.03842 |  |
| qwen3-235b | placebo | post | y_raw | constant | 1 | 266 | 14.69 | -768.3 | -764.8 | 0.05578 | True |
| qwen3-235b | placebo | post | y_raw | linear | 2 | 266 | 14.55 | -768.9 | -761.8 | 0.05598 | True |
| qwen3-235b | placebo | post | y_raw | log | 2 | 266 | 14.55 | -768.9 | -761.7 | 0.05599 | True |
| qwen3-235b | placebo | post | y_raw | spline | 4 | 266 | 14.55 | -765 | -750.6 | 0.05826 | True |
| qwen3-235b | placebo | post | y_raw | zhu | 6 | 266 | 14.26 | -766.3 | -744.8 | 0.05568 | True |
| qwen3-235b | placebo | post | y_adj | constant | 1 | 266 | 11.03 | -844.6 | -841 | 0.04194 |  |
| qwen3-235b | placebo | post | y_adj | linear | 2 | 266 | 11.01 | -843.2 | -836 | 0.04242 |  |
| qwen3-235b | placebo | post | y_adj | log | 2 | 266 | 11.01 | -843.1 | -836 | 0.04244 |  |
| qwen3-235b | placebo | post | y_adj | spline | 4 | 266 | 10.89 | -842 | -827.6 | 0.04261 |  |
| qwen3-235b | placebo | post | y_adj | zhu | 6 | 266 | 10.81 | -840 | -818.5 | 0.04349 |  |
| qwen3-235b | switch | full | y_raw | constant | 1 | 549 | 29.61 | -1601 | -1597 | 0.05412 | True |
| qwen3-235b | switch | full | y_raw | linear | 2 | 549 | 29.31 | -1605 | -1596 | 0.05384 | True |
| qwen3-235b | switch | full | y_raw | log | 2 | 549 | 28.69 | -1616 | -1608 | 0.05264 | True |
| qwen3-235b | switch | full | y_raw | spline | 4 | 549 | 27.71 | -1631 | -1614 | 0.0511 | True |
| qwen3-235b | switch | full | y_raw | zhu | 6 | 549 | 27.08 | -1640 | -1614 | 0.05078 | True |
| qwen3-235b | switch | full | y_adj | constant | 1 | 549 | 23.26 | -1734 | -1729 | 0.04255 |  |
| qwen3-235b | switch | full | y_adj | linear | 2 | 549 | 23.18 | -1734 | -1725 | 0.04279 |  |
| qwen3-235b | switch | full | y_adj | log | 2 | 549 | 22.98 | -1738 | -1730 | 0.04232 |  |
| qwen3-235b | switch | full | y_adj | spline | 4 | 549 | 22.57 | -1744 | -1727 | 0.04164 |  |
| qwen3-235b | switch | full | y_adj | zhu | 6 | 549 | 21.88 | -1757 | -1731 | 0.04075 |  |
| qwen3-235b | switch | post | y_raw | constant | 1 | 275 | 13.15 | -834.1 | -830.4 | 0.04831 | True |
| qwen3-235b | switch | post | y_raw | linear | 2 | 275 | 13.1 | -833.1 | -825.9 | 0.04835 | True |
| qwen3-235b | switch | post | y_raw | log | 2 | 275 | 13.09 | -833.4 | -826.1 | 0.04836 | True |
| qwen3-235b | switch | post | y_raw | spline | 4 | 275 | 13.07 | -829.7 | -815.3 | 0.04888 | True |
| qwen3-235b | switch | post | y_raw | zhu | 6 | 275 | 12.86 | -830.1 | -808.4 | 0.04953 | True |
| qwen3-235b | switch | post | y_adj | constant | 1 | 275 | 10.29 | -901.5 | -897.9 | 0.03805 |  |
| qwen3-235b | switch | post | y_adj | linear | 2 | 275 | 10.19 | -902.2 | -895 | 0.03777 |  |
| qwen3-235b | switch | post | y_adj | log | 2 | 275 | 10.21 | -901.7 | -894.5 | 0.03797 |  |
| qwen3-235b | switch | post | y_adj | spline | 4 | 275 | 10.14 | -899.6 | -885.1 | 0.03812 |  |
| qwen3-235b | switch | post | y_adj | zhu | 6 | 275 | 9.987 | -899.8 | -878.1 | 0.03851 |  |

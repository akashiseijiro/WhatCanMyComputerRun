"""PassMark averages for mainstream 2019+ GPUs and CPUs (plus the common Pascal/Maxwell cards).

Source: videocardbenchmark.net (Average G3D Mark) and cpubenchmark.net (Average CPU Mark),
snapshot taken 2026-11-01. One "name | score" per line, using PassMark's own spelling; the
lookup in static_scores.py normalizes names the same way the app does.

Rules for editing:
- Memory-size variants of one card collapse to one key (3060 8GB/12GB, 3050 6GB/8GB, ...): list
  only the most common variant.
- Integrated GPUs are deliberately NOT here: PassMark's iGPU numbers disagree with the
  owner-verified anchors in resolver.SYSTEM, so those still go through the AI resolver.
- Workstation/datacenter parts and ARM/Apple/Xeon/EPYC are out of scope.
"""

PASSMARK_SNAPSHOT = "2026-11-01"

GPU_DATA = """
GeForce RTX 5090 | 39001
GeForce RTX 5080 | 35654
GeForce RTX 5070 Ti | 32335
GeForce RTX 5070 | 28680
GeForce RTX 5060 Ti | 21844
GeForce RTX 5060 | 20592
GeForce RTX 5050 | 16714
GeForce RTX 4090 | 38024
GeForce RTX 4080 SUPER | 34211
GeForce RTX 4080 | 34442
GeForce RTX 4070 Ti SUPER | 31848
GeForce RTX 4070 Ti | 31512
GeForce RTX 4070 SUPER | 29941
GeForce RTX 4070 | 26852
GeForce RTX 4060 Ti | 22595
GeForce RTX 4060 | 19478
GeForce RTX 3090 Ti | 29195
GeForce RTX 3090 | 26461
GeForce RTX 3080 Ti | 26727
GeForce RTX 3080 | 24970
GeForce RTX 3070 Ti | 23159
GeForce RTX 3070 | 22063
GeForce RTX 3060 Ti | 20210
GeForce RTX 3060 | 16883
GeForce RTX 3050 | 12455
GeForce RTX 2080 Ti | 21399
GeForce RTX 2080 SUPER | 19390
GeForce RTX 2080 | 18569
GeForce RTX 2070 SUPER | 18120
GeForce RTX 2070 | 16053
GeForce RTX 2060 SUPER | 16455
GeForce RTX 2060 | 14070
GeForce RTX 2050 | 7730
GeForce GTX 1660 SUPER | 12655
GeForce GTX 1660 Ti | 12552
GeForce GTX 1660 | 11609
GeForce GTX 1650 SUPER | 10190
GeForce GTX 1650 Ti | 7544
GeForce GTX 1650 | 7865
GeForce GTX 1630 | 4972
GeForce GTX 1080 Ti | 18597
GeForce GTX 1080 | 15605
GeForce GTX 1070 Ti | 14684
GeForce GTX 1070 | 13511
GeForce GTX 1060 | 10013
GeForce GTX 1050 Ti | 6369
GeForce GTX 1050 | 5055
GeForce GTX 980 Ti | 13615
GeForce GTX 980 | 11069
GeForce GTX 970 | 9636
GeForce GTX 960 | 6149
GeForce GTX 950 | 5353
GeForce MX570 | 5754
GeForce MX550 | 4327
GeForce MX450 | 3711
GeForce RTX 5090 Laptop GPU | 28442
GeForce RTX 5080 Laptop GPU | 26322
GeForce RTX 5070 Ti Laptop GPU | 22532
GeForce RTX 5070 Laptop GPU | 19186
GeForce RTX 5060 Laptop GPU | 16777
GeForce RTX 5050 Laptop GPU | 13970
GeForce RTX 4090 Laptop GPU | 27024
GeForce RTX 4080 Laptop GPU | 24732
GeForce RTX 4070 Laptop GPU | 19461
GeForce RTX 4060 Laptop GPU | 17306
GeForce RTX 4050 Laptop GPU | 14190
GeForce RTX 3080 Ti Laptop GPU | 18791
GeForce RTX 3080 Laptop GPU | 16013
GeForce RTX 3070 Ti Laptop GPU | 17241
GeForce RTX 3070 Laptop GPU | 15008
GeForce RTX 3060 Laptop GPU | 13093
GeForce RTX 3050 Ti Laptop GPU | 10058
GeForce RTX 3050 Laptop GPU | 11966
GeForce RTX 2080 (Mobile) | 15014
GeForce RTX 2070 (Mobile) | 12357
GeForce RTX 2060 (Mobile) | 11353
GeForce GTX 1660 Ti (Mobile) | 10079
GeForce GTX 1650 (Mobile) | 6968
GeForce GTX 1070 (Mobile) | 10465
GeForce GTX 1060 (Mobile) | 8160
GeForce GTX 1050 Ti (Mobile) | 5918
GeForce GTX 1050 (Mobile) | 4463
Radeon RX 9070 XT | 26928
Radeon RX 9070 | 25380
Radeon RX 9070 GRE | 23312
Radeon RX 9060 XT | 19703
Radeon RX 9060 | 17726
Radeon RX 9050 | 11771
Radeon RX 7900 XTX | 31476
Radeon RX 7900 XT | 29124
Radeon RX 7900 GRE | 27473
Radeon RX 7800 XT | 24485
Radeon RX 7700 XT | 22780
Radeon RX 7700 | 20475
Radeon RX 7600 XT | 17363
Radeon RX 7600 | 16426
Radeon RX 7400 | 11897
Radeon RX 6950 XT | 28077
Radeon RX 6900 XT | 26640
Radeon RX 6800 XT | 25120
Radeon RX 6800 | 22046
Radeon RX 6750 XT | 20704
Radeon RX 6700 XT | 19710
Radeon RX 6700 | 18850
Radeon RX 6650 XT | 17096
Radeon RX 6600 XT | 16446
Radeon RX 6600 | 15031
Radeon RX 6500 XT | 9614
Radeon RX 6400 | 7754
Radeon RX 5700 XT | 16021
Radeon RX 5700 | 14195
Radeon RX 5600 XT | 13379
Radeon RX 5600 | 11569
Radeon RX 5500 XT | 9042
Radeon RX 5500 | 8832
Radeon RX 5300 | 7603
Radeon VII | 16165
Radeon RX Vega 64 | 13828
Radeon RX Vega 56 | 12913
Radeon RX 590 | 9273
Radeon RX 580 | 8782
Radeon RX 570 | 7905
Radeon RX 480 | 8525
Radeon RX 560 | 3689
Radeon RX 7900M | 22239
Radeon RX 7800M | 17607
Radeon RX 7700S | 15474
Radeon RX 7600S | 15613
Radeon RX 7600M XT | 14738
Radeon RX 7600M | 10937
Radeon RX 6850M XT | 17470
Radeon RX 6800M | 13301
Radeon RX 6800S | 15597
Radeon RX 6700M | 13686
Radeon RX 6700S | 14903
Radeon RX 6650M XT | 16081
Radeon RX 6650M | 15242
Radeon RX 6600M | 13759
Radeon RX 6600S | 13569
Radeon RX 6550M | 9674
Radeon RX 6500M | 7283
Radeon RX 5600M | 8829
Radeon RX 5500M | 6072
Intel Arc B580 | 16110
Intel Arc B570 | 14138
Intel Arc A770 | 13380
Intel Arc A750 | 12639
Intel Arc A580 | 12076
Intel Arc A380 | 6329
Intel Arc A310 | 5463
Intel Arc A770M | 11932
Intel Arc A730M | 9808
"""

CPU_DATA = """
Intel Core i9-14900KS | 59795
Intel Core i9-14900K | 58165
Intel Core i9-14900KF | 58054
Intel Core i9-14900F | 46398
Intel Core i9-14900 | 44500
Intel Core i9-14900T | 36117
Intel Core i7-14700K | 51901
Intel Core i7-14700KF | 51927
Intel Core i7-14700F | 41237
Intel Core i7-14700 | 40173
Intel Core i5-14600K | 38349
Intel Core i5-14600KF | 38217
Intel Core i5-14600 | 35761
Intel Core i5-14500 | 30456
Intel Core i5-14400F | 25393
Intel Core i5-14400 | 24989
Intel Core i3-14100F | 15400
Intel Core i3-14100 | 15089
Intel Core i9-13900KS | 60380
Intel Core i9-13900K | 58037
Intel Core i9-13900KF | 57401
Intel Core i9-13900F | 48029
Intel Core i9-13900 | 44491
Intel Core i7-13700K | 45577
Intel Core i7-13700KF | 45498
Intel Core i7-13700F | 37720
Intel Core i7-13700 | 35839
Intel Core i5-13600K | 37429
Intel Core i5-13600KF | 37295
Intel Core i5-13600 | 31017
Intel Core i5-13500 | 30655
Intel Core i5-13400F | 24868
Intel Core i5-13400 | 23897
Intel Core i3-13100F | 14654
Intel Core i3-13100 | 14115
Intel Core i9-12900KS | 43377
Intel Core i9-12900K | 41096
Intel Core i9-12900KF | 40429
Intel Core i9-12900F | 35748
Intel Core i9-12900 | 33626
Intel Core i7-12700K | 34227
Intel Core i7-12700KF | 33889
Intel Core i7-12700F | 30126
Intel Core i7-12700 | 29734
Intel Core i5-12600K | 27497
Intel Core i5-12600KF | 27501
Intel Core i5-12600 | 21285
Intel Core i5-12500 | 19685
Intel Core i5-12400F | 19524
Intel Core i5-12400 | 18833
Intel Core i3-12300 | 14365
Intel Core i3-12100F | 13953
Intel Core i3-12100 | 12529
Intel Core i9-11900K | 24890
Intel Core i9-11900KF | 24495
Intel Core i9-11900 | 22347
Intel Core i7-11700K | 24304
Intel Core i7-11700KF | 23731
Intel Core i7-11700F | 20746
Intel Core i7-11700 | 20571
Intel Core i5-11600K | 19473
Intel Core i5-11600KF | 19379
Intel Core i5-11600 | 17952
Intel Core i5-11500 | 17051
Intel Core i5-11400F | 16866
Intel Core i5-11400 | 16606
Intel Core i9-10980XE | 31886
Intel Core i9-10900K | 22213
Intel Core i9-10900KF | 22129
Intel Core i9-10900F | 19654
Intel Core i9-10900 | 19008
Intel Core i9-10850K | 21854
Intel Core i7-10700K | 18480
Intel Core i7-10700KF | 18264
Intel Core i7-10700F | 16084
Intel Core i7-10700 | 15966
Intel Core i5-10600K | 14236
Intel Core i5-10600KF | 14100
Intel Core i5-10600 | 13516
Intel Core i5-10500 | 12871
Intel Core i5-10400F | 12090
Intel Core i5-10400 | 11956
Intel Core i3-10300 | 9295
Intel Core i3-10100F | 8701
Intel Core i3-10100 | 8472
Intel Core Ultra 9 285K | 67231
Intel Core Ultra 9 285 | 57928
Intel Core Ultra 7 265K | 58571
Intel Core Ultra 7 265KF | 58428
Intel Core Ultra 7 265F | 49529
Intel Core Ultra 7 265 | 48423
Intel Core Ultra 5 245K | 42980
Intel Core Ultra 5 245KF | 43042
Intel Core Ultra 5 245 | 39401
Intel Core Ultra 5 235 | 36399
Intel Core Ultra 5 225F | 30910
Intel Core Ultra 5 225 | 30337
Intel Core Ultra 3 205 | 26082
AMD Ryzen 9 9950X3D | 70112
AMD Ryzen 9 9950X | 65705
AMD Ryzen 9 9900X3D | 56043
AMD Ryzen 9 9900X | 54283
AMD Ryzen 7 9850X3D | 41300
AMD Ryzen 7 9800X3D | 39912
AMD Ryzen 7 9700X | 36919
AMD Ryzen 5 9600X | 30024
AMD Ryzen 5 9600 | 29287
AMD Ryzen 5 9500F | 28110
AMD Ryzen 9 7950X3D | 62302
AMD Ryzen 9 7950X | 62125
AMD Ryzen 9 7900X3D | 50195
AMD Ryzen 9 7900X | 51207
AMD Ryzen 9 7900 | 48010
AMD Ryzen 7 7800X3D | 34279
AMD Ryzen 7 7700X | 35473
AMD Ryzen 7 7700 | 34312
AMD Ryzen 5 7600X | 28257
AMD Ryzen 5 7600 | 26964
AMD Ryzen 5 7500F | 26491
AMD Ryzen 5 7400F | 25652
AMD Ryzen 7 8700G | 31460
AMD Ryzen 7 8700F | 30829
AMD Ryzen 5 8600G | 25178
AMD Ryzen 5 8400F | 24361
AMD Ryzen 5 8500G | 21356
AMD Ryzen 9 5950X | 45240
AMD Ryzen 9 5900XT | 43869
AMD Ryzen 9 5900X | 38880
AMD Ryzen 9 5900 | 33967
AMD Ryzen 7 5800X3D | 28288
AMD Ryzen 7 5800XT | 28024
AMD Ryzen 7 5800X | 27655
AMD Ryzen 7 5700X3D | 26308
AMD Ryzen 7 5700X | 26539
AMD Ryzen 7 5700G | 24204
AMD Ryzen 7 5700 | 24185
AMD Ryzen 5 5600X3D | 21923
AMD Ryzen 5 5600XT | 22265
AMD Ryzen 5 5600X | 21819
AMD Ryzen 5 5600 | 21488
AMD Ryzen 5 5600GT | 20084
AMD Ryzen 5 5600G | 19617
AMD Ryzen 5 5500GT | 19051
AMD Ryzen 5 5500 | 19249
AMD Ryzen 5 4600G | 15926
AMD Ryzen 5 4500 | 15927
AMD Ryzen 3 5300G | 13004
AMD Ryzen 9 3950X | 38389
AMD Ryzen 9 3900XT | 32462
AMD Ryzen 9 3900X | 32463
AMD Ryzen 7 3800XT | 23390
AMD Ryzen 7 3800X | 22944
AMD Ryzen 7 3700X | 22375
AMD Ryzen 5 3600XT | 18501
AMD Ryzen 5 3600X | 18111
AMD Ryzen 5 3600 | 17646
AMD Ryzen 5 3500X | 13163
AMD Ryzen 5 3500 | 12746
AMD Ryzen 3 3300X | 12578
AMD Ryzen 3 3100 | 11504
Intel Core i9-14900HX | 43506
Intel Core i7-14700HX | 36358
Intel Core i7-14650HX | 33241
Intel Core i5-14500HX | 28645
Intel Core i5-14450HX | 23607
Intel Core i9-13980HX | 45230
Intel Core i9-13950HX | 40286
Intel Core i9-13900HX | 41321
Intel Core i7-13850HX | 35983
Intel Core i7-13700HX | 31532
Intel Core i7-13650HX | 29884
Intel Core i5-13600HX | 27477
Intel Core i5-13500HX | 27388
Intel Core i5-13450HX | 24325
Intel Core i9-12950HX | 30976
Intel Core i9-12900HX | 32707
Intel Core i7-12850HX | 30404
Intel Core i7-12800HX | 30964
Intel Core i7-12650HX | 22264
Intel Core i5-12450HX | 17591
Intel Core i9-13900H | 26997
Intel Core i7-13800H | 26030
Intel Core i7-13700H | 25784
Intel Core i7-13620H | 23136
Intel Core i5-13600H | 23123
Intel Core i5-13500H | 20901
Intel Core i5-13420H | 16730
Intel Core i9-12900H | 26521
Intel Core i7-12800H | 23539
Intel Core i7-12700H | 24911
Intel Core i7-12650H | 21204
Intel Core i5-12600H | 20341
Intel Core i5-12500H | 20208
Intel Core i5-12450H | 15842
Intel Core i9-11980HK | 21880
Intel Core i9-11900H | 19684
Intel Core i7-11850H | 19518
Intel Core i7-11800H | 19547
Intel Core i7-11600H | 15671
Intel Core i5-11400H | 15100
Intel Core i5-11260H | 15077
Intel Core i5-11300H | 10747
Intel Core i9-10980HK | 15049
Intel Core i9-10885H | 14171
Intel Core i7-10875H | 14348
Intel Core i7-10870H | 13907
Intel Core i7-10850H | 11470
Intel Core i7-10750H | 11416
Intel Core i5-10500H | 10884
Intel Core i5-10300H | 8166
Intel Core i5-10200H | 8004
Intel Core Ultra 9 290HX Plus | 58119
Intel Core Ultra 9 285HX | 56321
Intel Core Ultra 9 275HX | 55678
Intel Core Ultra 7 255HX | 47991
Intel Core Ultra 7 265HX | 47182
Intel Core Ultra 5 245HX | 37079
Intel Core Ultra 5 235HX | 40500
Intel Core Ultra 9 285H | 34215
Intel Core Ultra 9 185H | 28921
Intel Core Ultra 7 265H | 33955
Intel Core Ultra 7 255H | 30761
Intel Core Ultra 7 165H | 25858
Intel Core Ultra 7 155H | 24414
Intel Core Ultra 5 235H | 29701
Intel Core Ultra 5 225H | 27975
Intel Core Ultra 5 135H | 21886
Intel Core Ultra 5 125H | 19911
Intel Core 7 240H | 23962
Intel Core i7-1355U | 13817
Intel Core i5-1335U | 13734
Intel Core i7-1255U | 12915
Intel Core i5-1235U | 12390
Intel Core i7-1165G7 | 9725
Intel Core i5-1135G7 | 9284
AMD Ryzen 9 9955HX3D | 62121
AMD Ryzen 9 9955HX | 56339
AMD Ryzen 9 9850HX | 51722
AMD Ryzen 9 7945HX3D | 57507
AMD Ryzen 9 7945HX | 53748
AMD Ryzen 9 7940HX | 52923
AMD Ryzen 9 8945HX | 51260
AMD Ryzen 9 8940HX | 49389
AMD Ryzen 9 7845HX | 44209
AMD Ryzen 7 8840HX | 42156
AMD Ryzen 7 7840HX | 41530
AMD Ryzen 7 7745HX | 32358
AMD Ryzen 5 7645HX | 25777
AMD Ryzen AI 9 HX 375 | 35444
AMD Ryzen AI 9 HX 370 | 34949
AMD Ryzen AI 9 365 | 30334
AMD Ryzen AI 7 350 | 24995
AMD Ryzen AI 5 340 | 19625
AMD Ryzen 9 7940HS | 29702
AMD Ryzen 9 7940H | 28397
AMD Ryzen 7 7840HS | 28206
AMD Ryzen 7 7840H | 27306
AMD Ryzen 7 8845HS | 28251
AMD Ryzen 7 8840HS | 24510
AMD Ryzen 7 7840U | 24378
AMD Ryzen 7 8840U | 23380
AMD Ryzen 5 7640HS | 22662
AMD Ryzen 9 6980HX | 26817
AMD Ryzen 9 6900HX | 24010
AMD Ryzen 9 6900HS | 22716
AMD Ryzen 7 6800H | 22661
AMD Ryzen 7 6800HS | 22219
AMD Ryzen 7 6800U | 20653
AMD Ryzen 7 7735HS | 22118
AMD Ryzen 5 6600H | 17988
AMD Ryzen 9 5980HX | 23019
AMD Ryzen 9 5900HX | 21962
AMD Ryzen 7 5800H | 20429
AMD Ryzen 7 5800HS | 19324
AMD Ryzen 7 5800U | 17923
AMD Ryzen 5 5600H | 16325
AMD Ryzen 5 5600U | 14781
AMD Ryzen 5 5500U | 12574
AMD Ryzen 9 4900HS | 18707
AMD Ryzen 9 4900H | 18705
AMD Ryzen 7 4800H | 17788
AMD Ryzen 7 4800HS | 17806
AMD Ryzen 7 4800U | 16325
AMD Ryzen 5 4600H | 14050
AMD Ryzen 5 4600HS | 14169
AMD Ryzen 5 4600U | 12800
AMD Ryzen 7 3750H | 7905
AMD Ryzen 5 3550H | 7598
AMD Ryzen Z2 Extreme | 23200
AMD Ryzen Z2 | 25765
AMD Ryzen Z2 Go | 11090
AMD Ryzen Z1 Extreme | 24556
AMD Ryzen Z1 | 18258
"""

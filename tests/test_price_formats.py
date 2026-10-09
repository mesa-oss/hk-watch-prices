"""Price-format regression cases, taken from real HK dealer lines.

Run: python3 tests/test_price_formats.py
Each case is (line, expected_hkd, expected_usdt). None = must not be set.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from parser import extract_price  # noqa: E402

CASES = [
    # --- plain, must keep working ---
    ("5980/1A blue 680,000 hkd", 680_000, None),
    ("126506 ice blue n1 898k hkd", 898_000, None),
    ("15407or skeleton 19y HKD1.55m", 1_550_000, None),
    ("26735SG 2025 full set HKD3.276m", 3_276_000, None),
    ("⭐️126505 cho $443000 N4", 443_000, None),
    ("RM35-02 red 2019 $1780000", 1_780_000, None),
    ("AP 25820SP Used Full set , 830000HKD / 105800USDT", 830_000, 105_800),
    ("🟡 Rm33-03 2025 New 185k usdt", None, 185_000),
    ("5164g-001 2026 N3 1.1M", 1_100_000, None),
    ("15212NR N12/2025 FUll set  HKD 480K", 480_000, None),
    ("Hublot 905.JN.0001.RX Laferrari HKD:1586000", 1_586_000, None),
    ("11-03ntpt，2020y，new card 2.15m hkd", 2_150_000, None),
    ("235.032 2021y hkd158k", 158_000, None),
    ("PP 5124G-001 33.4x43mm, watch only. 105000HKD//13650USDT", 105_000, 13_650),
    ("5470P n6/2026 HKD $3.1m", 3_100_000, None),
    # --- dot as thousands separator ---
    ("PP 5205R Green - New 2025 - Price 410.000 HKD", 410_000, None),
    ("5205G Blue • New 3/2026 • 372.000 HKD", 372_000, None),
    ("5821/1A green 4/2026 710.000hkd", 710_000, None),
    ("15720cn new 2021 hkd 315.000", 315_000, None),
    ("RM 1.250.000 HKD full set", 1_250_000, None),
    ("USDT 52.000 5711", None, 52_000),
    # --- dot = decimal millions with the 'm' omitted (1 leading digit) ---
    ("26585CE blk 22y HKD3.147", 3_147_000, None),
    ("5164G N10/2025  used fs hkd1.135", 1_135_000, None),
    # --- comma as decimal point ---
    ("5270P-016 N5/26 HKD1,82m", 1_820_000, None),
    ("7118/1200R white $1,21m hkd Used2020", 1_210_000, None),
    ("26674sg N10/2025 HKD 2,26m", 2_260_000, None),
    ("126500 2,5m hkd", 2_500_000, None),
    ("RM 1,5m", 1_500_000, None),
    # --- trailing 'U' = USDT ---
    ("Rm67-02 white 2020 used 419k u", None, 419_000),
    ("5822p n11/25 new 1.135m hkd/146.2k U", 1_135_000, 146_200),
    ("126518yml N11/25 new 493k hkd/63.5k U", 493_000, 63_500),
    ("126500 white 2025 used 25.5ku", None, 25_500),
    # --- USDT typos ---
    ("Rm010 rose gold 2007 fullset 130k ustd", None, 130_000),
    # --- explicit USD (not HKD) ---
    ("RM65-01 RG/CA, 2023 Used Full Set – USD 265K", None, 265_000),
    ("rm72-01 ti, 2026-03 – HKD 2,450,000 / USD 315,000", 2_450_000, 315_000),
    ("5308G N2/2025y HKD 2.55M USD", 2_550_000, None),
    # --- 萬 / w (×10,000) ---
    ("5072R 5/2026 179W hkd", 1_790_000, None),
    ("RM30-01white 2025y used full set 263万", 2_630_000, None),
    ("RM30-01 2025 263万人民币", 2_866_700, None),
    ("49150-000W-9015 2018y fullset 144k hkd", 144_000, None),
    # --- RMB → HKD (×1.09) ---
    ("26238Ti green 2021y rmb 225k", 245_250, None),
    ("Hublot 646.QK.1230.VR.CNY 2026 new full set 258k hkd", 258_000, None),
    # --- 'used' must not be read as a U suffix ---
    ("126610LN 2023 98k used full set", 98_000, None),
    # --- millions with the 'm' omitted ---
    ("RM07-01 Black Ceramic Red lip 2/26 HKD1.94 usdt250k", 1_940_000, 250_000),
    ("26586TI blue 2023 hkd1.69", 1_690_000, None),
    ("5712/1a Blue 2021 used fullset HKD1.0", 1_000_000, None),
    ("5990/1r N4/2026 New 2.32 HKD", 2_320_000, None),
    ("5980/1400g, 2022 New, HKD 4.40 Million", 4_400_000, None),
    ("FPJ Octa Lune 2023, HKD 1.51 mil", 1_510_000, None),
    ("5160/500R 2024 full set HKD1.42 m", 1_420_000, None),
    # --- n<month>.<yy> date right before the price must not be read ---
    ("124060 n1.26 HKD99k", 99_000, None),
    ("228345rbr Green Roman n2.26 HKD593k", 593_000, None),
    # --- USDT dot-thousands (Boss Luxury style) ---
    ("Patek Philippe 7119G // Naked// Good Condition//9.600Usdt", None, 9_600),
    ("Patek Philippe 5711/1A // Full Set// NOS 2019 // 139.000Usdt", None, 139_000),
    ("Price: 45.000 USDt // 350.000 HKD", 350_000, 45_000),
    # --- marker between two numbers ---
    ("830000 HKD 105800 USDT", 830_000, 105_800),
    ("HKD 1.94 USDT 250k", 1_940_000, 250_000),
    # --- traps: karat gold, water depth, mm ---
    ("126518 18k yellow gold 2025 380k", 380_000, None),
    ("Submariner 300m 2024 HKD 120k", 120_000, None),
    ("Diver 50m water resist", None, None),
    ("41mm 126334 2024 HKD 108k", 108_000, None),
    ("680 000 hkd 5711", 680_000, None),
    # --- found by the old-vs-new diff ---
    ("⭐️5712/1R 2/2025  New HKD 1,960M", 1_960_000, None),
    ("5131/1P-001 - HKD$1,025m (04/2017) Band New", 1_025_000, None),
    ("5980/60G-001 Blue - HKD$1,36m  (02/2026", 1_360_000, None),
    ("🇭🇰4000U/000R-B516  2024 Full Set Used HKD 219K", 219_000, None),
    ("Rm 030 ntpt candy 2022yr278000usdt", None, 278_000),
    ("030rg2022y175kusdt", None, 175_000),
    ("4600V/200R-H134  5/2026//New//HKD//383k", 383_000, None),
    ("Rm07-01 white Ceramics mop 2/2026 New $343k usdt", None, 343_000),
    ("26638fo 2025 hkd2.14m usd275k", 2_140_000, 275_000),
    ("Girard Perregaux 49805 Automatic 18k Rose Gold", None, None),
    ("Yacht-Master II 116689 18k White/ Platinum Bezel", None, None),
    ("16014 year '83 W&P (no box) 5k", 5_000, None),
    ("26420SO Smoke n4/26 hk$324kk", 324_000, None),
    ("P P 4897G—001, 33 mm, reference 58, dual P, watch only,86100HKD", 86_100, None),
    ("Used 25977st blk,2016y,585K HKD", 585_000, None),
    ("PP 5135 J--001, automatic machine, 18k gold, 38x51mm, 2008, with box.189000", 189_000, None),
    ("RM07-01 Sakura MOP Lips Watch Only $2,850,000RMB", 3_106_500, None),
    ("5164g n4/n5 $1.145/1.155m", 1_145_000, None),
    ("Pam01384 N3 29900HKD 41600$ -33%", 29_900, None),
    ("Size:31m", None, None),
    # --- found by the post-load audit ---
    ("126539TBR 01/2026 New 1,180,000HK$/151,500US$", 1_180_000, 151_500),
    ("WSPN0012 08/2026 New 33,200 -10% = 29,880HK$/3,800US$", 29_880, 3_800),
    ("15468BA Rainbow,2026,1.9M HKD", 1_900_000, None),
    ("26643TI, N4/26,2.78M HKD", 2_780_000, None),
    ("126508 YML, N8/26,550K HKD", 550_000, None),
    ("7200/50G Beige, N6,205K HKD", 205_000, None),
    ("278274G Pink Jub N2,126K  HKD", 126_000, None),
    ("126680,7/2026,195000 HKD,both tag,full sticker", 195_000, None),
    ("126710blro Oys n5/25 hk198k unadj NOS", 198_000, None),
    ("26240or blue full gold 2024y HK935k", 935_000, None),
    ("278274 G pink jub hkd126kN6/127kN7", 126_000, None),
    ("47200/000j-8444 watch only 78000hkdw", 78_000, None),
    ("5271/12P Red,2026,4450000 HKD", 4_450_000, None),
    ("RM35-01 WHITE NTPT,2019,4080000 HKD", 4_080_000, None),
    ("RM07-01 Red Lips RG USED 2020 HKD 1,360.000", 1_360_000, None),
    ("26534ti green 2021 full set 💰1.465k hkd", 1_465_000, None),
    ("RM11-02 Rose gold , Watch only / $1280,000 HKD", 1_280_000, None),
    ("RM65-01 NTPT Black, 2023. 2550,000 HKD", 2_550_000, None),
    ("5968A 2019 full set HKD1.004k", 1_004_000, None),
    ("5271/11p blue 2023 used full set hkd3.90k", 3_900, None),
    ("5164G 2024Y HKD1.04K", 1_040, None),
    ("7118/1200R champ N5 HKD1,230,00", 1_230, None),
    ("7118/1200R champ 5/2026 HKD 1,25K", 1_250, None),
    ("RM11-03 ti, 2020 full set - hkd 1.63k", 1_630, None),
    # --- second audit pass ---
    ("15510ST Black,2023,345K HKD", 345_000, None),
    ("26715ST Ice Blue,2025,470K HKD", 470_000, None),
    ("26591TI,2021,225K USDT", None, 225_000),
    ("126331 Wim Oys,2023,320K HKD 🏷️", 320_000, None),
    ("5905R-N5-505000hkd", 505_000, None),
    ("6007GYellow-2026-06-2100000hkd", 2_100_000, None),
    ("6196P-N8-375k hkd", 375_000, None),
    ("126334 ombre green jub 07/26 -162,000 HKD", 162_000, None),
    ("RM07-01 RG snow diamond black lip 2026 new -330k usdt", None, 330_000),
    ("278271NG WHT Jub N6/152k", 152_000, None),
    ("5267/200A green n6/545k  ///n7/550k", 545_000, None),
    ("HPI00449 open date532,000 HKD", 532_000, None),
    ("26240bc ice blue 24y1.3m", 1_300_000, None),
    ("116689white 10.5links 2020y255k", 255_000, None),
    ("4520V/210A-B483 2025 full set new205k hkd", 205_000, None),
    ("14840BC T-drill Sapphire naked1.12m HKD", 1_120_000, None),
    ("2025/10 180000hkd", 180_000, None),
    # ambiguous → better nothing than a wrong price
    ("26531ti salmon, 2022 y , HKD  190,0000", None, None),
    ("5271/13P-001 2016y   HKD  6,9700,000", None, None),
    ("278273NG Blk Jub N3149K", None, None),
    ("5124G-001, 2020", None, None),
    # --- third audit pass ---
    ("7118/1200R-010 (Champ) 2024y   HKD 1,26,000", None, None),
    ("AP 26589RO Ltd 20pcs NOS conditions HK$1,96,000", None, None),
    ("- 5216R 2021 new unworn ｜HKD 5,870,00", 5_870, None),
    ("6104G 2015 blue full set used 6.32k hkd", 6_320, None),
    ("277200 lavender n7 🏷️ $59.5", None, None),
    ("116400 GV BLK 2010\t11.5\tHKD 68,800.00", 68_800, None),
    ("216570 BLK 2012\t9.5\tHKD 61,800.00", 61_800, None),
    ("103949 N4 HKD 51000k", 51_000, None),
    ("RM67-02 Black Ogil 💰421000k usdt", None, 421_000),
    ("116588TBR 2019 year $1,4HKD", 1_400_000, None),
    ("16202ST  blhkd3452 50th  Used  hkd620k", 3_452, None),
    ("126500white N7 adj M size $2200", 2_200, None),
    ("Patek Philippe 5961R brand new, 131,800 USDT or 102,3000 HKD", 3_000, 131_800),
    ("used rm52-06 White mask 20201.48m usdt", None, None),
    ("Hublot 521.NX.7071.RX N9 55.552k HKD", 55_552, None),
    ("127334 n5 HKD197,5k", 197_500, None),
    ("226659 n7 295 000 hkd", 295_000, None),
    ("RM07-01 ROM Diamond mop White 2021year $405000U", None, 405_000),
    ("Rm07-01 Bright Night明夜 5/2026 usdt～405k", None, 405_000),
    ("RM65-01 2024 HKD 2,450,000U", None, 2_450_000),
    ("126333g Black Jub N6 🏷️ $169,5k", 169_500, None),
    ("278383ng white jub n7 204. 5k🏷️", 204_500, None),
    ("26405CE Green,2020-12,330K HKD", 330_000, None),
    ("4520V/210A-B128 Blue,2026-8,268K HKD", 268_000, None),
    ("      1190000 N6", 1_190_000, None),

]

# US / WDG markets: '$' means USD (dollar_is_usd=True)
USD_CASES = [
    ("116334 41mm DJs White Stick Under 9k", None, 9_000),
    ("Fresh Daytona 116500 white 2024 17k shipped", None, 17_000),
    ("WDG seller 305.000 HKD", 305_000, None),
    ("Retail Ready 326934 Oyster Black Dial 08/2022 $17,000 + label", None, 17_000),
    ("Asking $15995 CAD / $11.7k USD", None, 11_700),
    ("Amount: < usd 40k", None, 40_000),
    ("• Water Resistance: 50m", None, None),
    ("Case: 40mm Solid 18k Yellow Gold", None, None),
    ("16233 Serial E Black Diamond W&P (no box) 6,7k", None, 6_700),
    ("16014 year '83 W&P (no box) 5k", None, 5_000),
]


def main() -> int:
    bad = 0
    total = 0
    for cases, usd in ((CASES, False), (USD_CASES, True)):
        for line, exp_h, exp_u in cases:
            total += 1
            h, u, _e, _ = extract_price(line, dollar_is_usd=usd)
            if (h, u) != (exp_h, exp_u):
                bad += 1
                print(f"FAIL  {line!r}\n      got hkd={h} usdt={u}  want hkd={exp_h} usdt={exp_u}")
    print(f"\n{total - bad}/{total} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

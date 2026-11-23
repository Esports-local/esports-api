"""선수 이름 사전 (코드로 관리): op.gg·중계 화면의 영어 이름 → 한국어 해설 표기.

여기에 적은 것을 sync_players 가 Player 표에 넣는다 (api 컨테이너를 띄울 때 자동 실행, 한국어 표기는 이 파일이 기준).
새 선수는 여기에 한 줄 추가한다. 대소문자는 가리지 않는다. 없는 선수는 숏폼 자막에 영어 그대로 나온다
(sync_players 가 경기 정보에 나왔는데 여기 없는 선수를 알려 준다).
"""

PLAYERS_KO = {
    # LCK
    "Faker": "페이커", "Oner": "오너", "Keria": "케리아", "Gumayusi": "구마유시", "Zeus": "제우스",
    "Doran": "도란", "Peyz": "페이즈", "Smash": "스매시",
    "Kiin": "기인", "Canyon": "캐니언", "Chovy": "쵸비", "Ruler": "룰러", "Duro": "듀로", "Lehends": "리헨즈",
    "Peanut": "피넛", "Kanavi": "카나비", "Zeka": "제카", "Viper": "바이퍼", "Delight": "딜라이트",
    "PerfecT": "퍼펙트", "Cuzz": "커즈", "Bdd": "비디디", "deokdam": "덕담", "Peter": "피터", "Aiming": "에이밍",
    "Siwoo": "시우", "Lucid": "루시드", "ShowMaker": "쇼메이커", "BeryL": "베릴",
    "Kingen": "킹겐", "Clear": "클리어", "Raptor": "랩터", "VicLa": "빅라", "Diable": "디아블", "Kellin": "켈린",
    "Teddy": "테디", "Rich": "리치", "DuDu": "두두", "Pyosik": "표식", "BuLLDoG": "불독", "Berserker": "버서커",
    "Life": "라이프", "Clozer": "클로저", "Morgan": "모건",
    # LPL · 국제 대회
    "Bin": "빈", "Knight": "나이트", "Elk": "엘크", "ON": "온", "Scout": "스카웃", "Tarzan": "타잔",
    "JackeyLove": "재키러브",
}

"""홍인기 유튜브 자막 분석 스크립트"""

import json
import re
from collections import Counter

# 키워드 카테고리
KEYWORDS = {
    "매매 타이밍": [
        "돌파", "눌림", "상따", "하따", "장초반", "장후반", "9시", "10시", "11시",
        "시초가", "종가", "장중", "동시호가", "갭상", "갭하", "오전", "오후"
    ],
    "기술적 지표": [
        "이평선", "5일선", "10일선", "20일선", "60일선", "120일선", "거래량",
        "rsi", "볼린저", "macd", "스토캐스틱", "이동평균", "ma", "분봉", "일봉",
        "봉차트", "캔들", "양봉", "음봉", "장대양봉", "장대음봉", "십자가", "도지"
    ],
    "매매 전략": [
        "손절", "익절", "비중", "물타기", "분할매수", "분할매도", "추매",
        "손익비", "승률", "원칙", "리스크", "자금관리", "포지션", "진입", "청산"
    ],
    "시장 분석": [
        "주도주", "테마", "섹터", "시장", "코스피", "코스닥", "외국인", "기관",
        "수급", "거래대금", "시총", "대장주", "후발주"
    ],
    "차트 패턴": [
        "쌍바닥", "쌍봉", "삼각수렴", "박스권", "지지", "저항", "추세선",
        "상승추세", "하락추세", "횡보", "돌파", "이탈", "눌림목"
    ],
    "호가창/체결": [
        "호가창", "매수세", "매도세", "체결강도", "허매수", "허매도",
        "대량체결", "프로그램", "알고리즘"
    ],
    "심리/멘탈": [
        "멘탈", "감정", "욕심", "공포", "탐욕", "인내", "기다림", "확신",
        "손실", "수익", "계좌", "복구"
    ]
}

def load_transcripts():
    """자막 데이터 로드"""
    with open("data/youtube_transcripts/honginggi_transcripts.json", 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze_keywords(transcripts):
    """키워드 빈도 분석"""
    all_text = " ".join([t['transcript'] for t in transcripts if t['transcript']])
    all_text_lower = all_text.lower()

    results = {}
    for category, keywords in KEYWORDS.items():
        category_counts = {}
        for kw in keywords:
            count = all_text_lower.count(kw.lower())
            if count > 0:
                category_counts[kw] = count
        results[category] = dict(sorted(category_counts.items(), key=lambda x: x[1], reverse=True))

    return results

def extract_trading_rules(transcripts):
    """매매 규칙/원칙 추출"""
    rules = []
    patterns = [
        r'원칙[은이가]?\s*(.{10,50})',
        r'규칙[은이가]?\s*(.{10,50})',
        r'절대[로]?\s*(.{10,50})',
        r'반드시\s*(.{10,50})',
        r'무조건\s*(.{10,50})',
        r'항상\s*(.{10,50})',
        r'손절[은이가을]?\s*(.{10,50})',
        r'익절[은이가을]?\s*(.{10,50})',
    ]

    for t in transcripts:
        if not t['transcript']:
            continue
        text = t['transcript']
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                rules.append({
                    'video': t['title'],
                    'rule': m.strip()
                })

    return rules

def extract_specific_numbers(transcripts):
    """구체적인 수치/비율 추출"""
    numbers = []
    patterns = [
        r'(\d+)%\s*(손절|익절|수익|손실)',
        r'(손절|익절|수익|손실)[은이가을]?\s*(\d+)%',
        r'(\d+)분봉',
        r'(\d+)일선',
        r'(\d+)틱',
        r'비중[은이가을]?\s*(\d+)%',
        r'(\d+)%\s*비중',
    ]

    for t in transcripts:
        if not t['transcript']:
            continue
        text = t['transcript']
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                numbers.append({
                    'video': t['title'][:30],
                    'match': str(m)
                })

    return numbers

def summarize_by_video(transcripts):
    """영상별 핵심 키워드"""
    summaries = []
    for t in transcripts:
        if not t['transcript']:
            continue

        text_lower = t['transcript'].lower()
        found_keywords = []

        for category, keywords in KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    found_keywords.append(kw)

        summaries.append({
            'title': t['title'],
            'url': t['url'],
            'length': len(t['transcript']),
            'top_keywords': list(set(found_keywords))[:15]
        })

    return summaries

def main():
    print("="*60)
    print("대왕개미 홍인기 유튜브 자막 분석")
    print("="*60)

    transcripts = load_transcripts()

    # 1. 전체 키워드 분석
    print("\n[1] 카테고리별 키워드 빈도")
    print("-"*40)
    keyword_analysis = analyze_keywords(transcripts)
    for category, counts in keyword_analysis.items():
        if counts:
            print(f"\n📌 {category}:")
            for kw, count in list(counts.items())[:10]:
                print(f"   - {kw}: {count}회")

    # 2. 매매 규칙 추출
    print("\n" + "="*60)
    print("[2] 추출된 매매 원칙/규칙 (샘플)")
    print("-"*40)
    rules = extract_trading_rules(transcripts)
    seen = set()
    count = 0
    for r in rules:
        rule_text = r['rule'][:50]
        if rule_text not in seen and count < 20:
            print(f"• {rule_text}...")
            seen.add(rule_text)
            count += 1

    # 3. 구체적 수치
    print("\n" + "="*60)
    print("[3] 언급된 구체적 수치")
    print("-"*40)
    numbers = extract_specific_numbers(transcripts)
    num_counter = Counter([str(n['match']) for n in numbers])
    for num, count in num_counter.most_common(15):
        print(f"   {num}: {count}회")

    # 4. 영상별 요약
    print("\n" + "="*60)
    print("[4] 영상별 핵심 주제")
    print("-"*40)
    summaries = summarize_by_video(transcripts)
    for s in summaries[:10]:
        print(f"\n📺 {s['title'][:40]}...")
        print(f"   키워드: {', '.join(s['top_keywords'][:8])}")

    # 분석 결과 저장
    analysis_result = {
        'keyword_analysis': keyword_analysis,
        'rules_sample': rules[:50],
        'numbers': numbers[:50],
        'video_summaries': summaries
    }

    with open("data/youtube_transcripts/honginggi_analysis.json", 'w', encoding='utf-8') as f:
        json.dump(analysis_result, f, ensure_ascii=False, indent=2)

    print("\n" + "="*60)
    print("분석 완료! 저장: data/youtube_transcripts/honginggi_analysis.json")

if __name__ == "__main__":
    main()

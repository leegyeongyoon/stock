"""YouTube 채널에서 자막 추출하는 스크립트"""

import os
import json
import scrapetube
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

# 채널 ID (대왕개미 홍인기)
CHANNEL_URL = "https://www.youtube.com/@대왕개미홍인기"

# 출력 디렉토리
OUTPUT_DIR = "data/youtube_transcripts"


def get_channel_videos(channel_url: str, limit: int = 30):
    """채널에서 최신 영상 목록 가져오기"""
    print(f"채널에서 영상 목록 가져오는 중... (최대 {limit}개)")

    # URL에서 채널 핸들 추출
    if "@" in channel_url:
        # @handle 형식
        handle = channel_url.split("@")[-1]
        videos = scrapetube.get_channel(channel_username=handle, limit=limit)
    else:
        videos = scrapetube.get_channel(channel_url=channel_url, limit=limit)

    video_list = []
    for video in videos:
        video_id = video["videoId"]
        title = video.get("title", {}).get("runs", [{}])[0].get("text", "제목 없음")
        video_list.append({
            "id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}"
        })
        print(f"  - {title[:50]}...")

        if len(video_list) >= limit:
            break

    print(f"총 {len(video_list)}개 영상 발견")
    return video_list


def get_transcript(video_id: str) -> str | None:
    """영상에서 자막 추출"""
    try:
        # 새 API: 인스턴스 생성 후 사용
        api = YouTubeTranscriptApi()

        # 한국어 자막 시도
        try:
            transcript = api.fetch(video_id, languages=['ko'])
            text = " ".join([entry.text for entry in transcript])
            return text
        except:
            pass

        # 영어 자막 시도
        try:
            transcript = api.fetch(video_id, languages=['en'])
            text = " ".join([entry.text for entry in transcript])
            return text
        except:
            pass

        # 자막 목록 확인
        try:
            transcript_list = api.list(video_id)
            for t in transcript_list:
                transcript = t.fetch()
                text = " ".join([entry.text for entry in transcript])
                return text
        except:
            pass

        return None

    except TranscriptsDisabled:
        print(f"    자막 비활성화됨")
        return None
    except NoTranscriptFound:
        print(f"    자막 없음")
        return None
    except VideoUnavailable:
        print(f"    영상 접근 불가")
        return None
    except Exception as e:
        print(f"    오류: {e}")
        return None


def main():
    # 출력 디렉토리 생성
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 채널에서 영상 목록 가져오기
    videos = get_channel_videos(CHANNEL_URL, limit=30)

    # 자막 추출
    results = []
    success_count = 0

    for i, video in enumerate(videos):
        print(f"\n[{i+1}/{len(videos)}] {video['title'][:40]}...")

        transcript = get_transcript(video['id'])

        if transcript:
            success_count += 1
            results.append({
                "video_id": video['id'],
                "title": video['title'],
                "url": video['url'],
                "transcript": transcript,
            })
            print(f"    ✓ 자막 추출 성공 ({len(transcript)} 글자)")
        else:
            results.append({
                "video_id": video['id'],
                "title": video['title'],
                "url": video['url'],
                "transcript": None,
            })

    # 결과 저장
    output_file = os.path.join(OUTPUT_DIR, "honginggi_transcripts.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"완료! {success_count}/{len(videos)}개 영상 자막 추출 성공")
    print(f"저장 위치: {output_file}")

    # 자막 있는 것만 별도 텍스트 파일로 저장
    txt_file = os.path.join(OUTPUT_DIR, "honginggi_all_transcripts.txt")
    with open(txt_file, 'w', encoding='utf-8') as f:
        for r in results:
            if r['transcript']:
                f.write(f"\n{'='*60}\n")
                f.write(f"제목: {r['title']}\n")
                f.write(f"URL: {r['url']}\n")
                f.write(f"{'='*60}\n\n")
                f.write(r['transcript'])
                f.write("\n\n")

    print(f"텍스트 파일: {txt_file}")


if __name__ == "__main__":
    main()

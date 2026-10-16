# Playground 오디오 샘플

Playground의 오디오 분석 예제는 로컬 정적 자산 `sample-audio.wav`를 사용한다.
두 짧은 발화를 재생하고, **나간 시각(세 시)**과 **외출 시간(세 시간)**을 구분해 답하는지 확인한다.
이 예제는 실제 인식 품질을 보증하거나 자동으로 추론 요청을 보내지 않는다.

## 원본과 사용 조건

- 녹음자: **HappyMidnight**, Lingua Libre / Wikimedia Commons.
- 발화 1: 「그들은 세시에 나갔어요.」
  - 원본 파일: [LL-Q9176 (kor)-HappyMidnight-그들은 세시에 나갔어요..wav](https://commons.wikimedia.org/wiki/File:LL-Q9176_(kor)-HappyMidnight-그들은_세시에_나갔어요..wav)
- 발화 2: 「그들은 세시간을 나갔다 왔어요.」
  - 원본 파일: [LL-Q9176 (kor)-HappyMidnight-그들은 세시간을 나갔다 왔어요.wav](https://commons.wikimedia.org/wiki/File:LL-Q9176_(kor)-HappyMidnight-그들은_세시간을_나갔다_왔어요.wav)
- 양쪽 모두 Lingua Libre에서 공개한 **CC0 1.0** 발음 녹음을 활용한다. [라이선스](https://creativecommons.org/publicdomain/zero/1.0/deed.ko)
- 원본 두 개를 순서대로 이어 붙이고 사이에 0.45초 무음을 추가한 뒤, 음성 처리를 위해 mono/16 kHz/16-bit PCM WAV로 변환했다. 음성 내용 자체는 편집하지 않았다.
- 원본은 온라인 재생이나 API 전송 시 외부에서 실시간으로 가져오지 않는다. 두 checked-in 자산(`assets/demos/inputs/sample-audio.wav`, `ui/control-plane/src/playgroundAssets/sample-audio.wav`)은 동일한 바이너리이다.

## 예상 동작

- 갤러리의 샘플은 사용자 선택으로만 재생하고, 화면의 「입력에 적용」은 준비 단계이다.
- `GET /v1/models`에서 오디오 입력, WAV 형식, 크기와 첨부 수 제한을 지원한 모델만 적용할 수 있다.
- 실제 사용자가 「보내기」를 선택해야 기존 `/v1/chat/completions`로 `input_audio`를 전송한다.
- 두 발화의 정보는 일상적인 문장 예시다. 별도의 STT 서비스, 외부 파일 저장소 또는 사용자 녹음은 만들지 않는다.

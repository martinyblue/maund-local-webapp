# MAUND Local Web App

이 문서는 `컴퓨터를 잘 모르는 사람`도 그대로 따라 할 수 있도록, 아주 자세하게 작성한 사용 설명서입니다.  
이 프로그램은 `내 컴퓨터 안에서만` 실행되는 로컬 웹앱입니다. 서버에 올리는 방식이 아니라, 내 컴퓨터에서 분석 화면을 열고 사용하는 방식입니다.
현재 저장소 기준 버전은 `VERSION` 파일에 들어 있으며, 앱 화면 상단과 GitHub 릴리스 태그에서도 같은 버전을 확인할 수 있습니다.

## 1. 이 프로그램이 하는 일

이 프로그램은 두 가지 방식으로 MAUND 분석 결과를 만들어 줍니다.

### 방식 1. 기본 분석

기존에 사용하던 일반 MAUND 방식입니다.  
한 번에 하나의 target sequence를 기준으로 분석합니다.

- FASTQ 폴더
- sequence xlsx 파일
- sample TALE xlsx 파일
- TALE array xlsx 파일
- sample 번호 범위
- target sequence
- editor type

### 방식 2. heatmap 분석

`N234`, `F260` 처럼 block 구조가 들어 있는 xlsx를 읽어서 block별로 따로 분석합니다.  
block은 여러 개여도 되고, `N234` 하나만 있어도 됩니다.  
이 방식에서는 block마다 별도 HTML 파일이 만들어지고, 그 HTML 안에 `기존 분석 결과 + 새 heatmap` 이 함께 들어갑니다.

- FASTQ 폴더
- sequence xlsx 파일
- sample TALE xlsx 파일
- TALE array xlsx 파일
- sample 번호 범위 또는 제외 번호
- editor type
- block 이름과 desired product sequence 보완값(필요할 때만)

실행이 끝나면 내 컴퓨터 안에 결과 폴더가 생깁니다.  
결과 폴더 이름은 아래처럼 날짜와 시간이 함께 들어갑니다.

```text
maund_260315_153045
```

즉:

- `260315` 는 날짜
- `153045` 는 생성 시간

입니다.  
같은 날 여러 번 돌려도 시간이 다르면 서로 다른 새 폴더가 만들어집니다.

결과 폴더 안에는 보통 다음 항목이 들어 있습니다.

- `merged_fastq`
- `maund_out`
- `logs`
- `tables`
- `merge_stats_<tag>.tsv`
- `run_status_<tag>.tsv`
- `edited_reads_<tag>.tsv`
- `sample_editing_<editor>_<targetslug>_<tag>.tsv`
- `ranked_haplotypes_<editor>_<targetslug>_<tag>.tsv`
- `haplotype_render_rows_<editor>_<targetslug>_<tag>.tsv`
- `haplotype_colored_by_combo_<editor>_<targetslug>_<tag>.html`
- `analysis_flow_<tag>.md`

heatmap 분석일 때는 block마다 아래 파일도 각각 따로 생깁니다.

- `sample_editing_n234_<tag>.tsv`
- `ranked_haplotypes_n234_<tag>.tsv`
- `heatmap_matrix_n234_<tag>.tsv`
- `heatmap_detail_n234_<tag>.tsv`
- `report_n234_<tag>.html`
- `sample_editing_f260_<tag>.tsv`
- `ranked_haplotypes_f260_<tag>.tsv`
- `heatmap_matrix_f260_<tag>.tsv`
- `heatmap_detail_f260_<tag>.tsv`
- `report_f260_<tag>.html`

## 2. GitHub에서 다운로드하는 방법

GitHub를 잘 모르는 사람도 아래 순서대로 하면 됩니다.  
이 저장소를 받기 위해 `GitHub 계정`은 꼭 필요하지 않습니다.

### 방법 A. 권장 방법: Releases 에서 버전별로 받기

버전이 분명하게 표시된 파일을 받고 싶다면 이 방법이 가장 좋습니다.

1. GitHub 저장소 페이지를 엽니다.
2. 오른쪽 영역 또는 상단 메뉴에서 `Releases` 를 누릅니다.
3. 가장 위에 있는 최신 버전을 찾습니다. 예: `v0.1.0`
4. 해당 버전 페이지를 엽니다.
5. `Source code (zip)` 또는 따로 첨부된 배포 파일이 있으면 그것을 누릅니다.
6. 다운로드가 끝나면 `다운로드` 폴더를 엽니다.
7. ZIP 파일을 더블클릭해 압축을 풉니다.
8. 압축이 풀린 폴더를 연 뒤 실행 파일을 누릅니다.

### 방법 B. 일반 ZIP으로 내려받기

1. GitHub 저장소 페이지를 엽니다.
2. 화면 오른쪽 위 또는 파일 목록 위쪽에 있는 초록색 `Code` 버튼을 누릅니다.
3. 펼쳐진 메뉴에서 `Download ZIP` 을 누릅니다.
4. 잠시 기다리면 컴퓨터에 ZIP 파일이 다운로드됩니다.
5. 다운로드가 끝나면 `다운로드` 폴더를 엽니다.
6. 방금 받은 ZIP 파일을 더블클릭합니다.
7. 같은 위치에 압축이 풀린 새 폴더가 생깁니다.
8. 그 새 폴더를 엽니다.
9. 그 안에서 `run_maund_local_app.command` 또는 `run_maund_local_app.bat` 파일을 실행하면 됩니다.

### 방법 C. Git을 아는 사람이 받는 방법

터미널 또는 명령 프롬프트를 사용할 줄 아는 사람은 저장소 주소로 `git clone` 해도 됩니다.  
하지만 컴퓨터 사용이 익숙하지 않다면 `방법 A` 를 쓰는 것이 가장 쉽습니다.

### ZIP을 받은 뒤 꼭 해야 하는 것

압축 파일 안에서 바로 실행하지 말고, 먼저 `압축 해제된 폴더` 를 연 뒤 그 안에서 실행하세요.  
즉, ZIP 파일을 더블클릭해 새 폴더가 생긴 다음 그 폴더 안의 실행 파일을 눌러야 합니다.

## 3. 시작하기 전에 준비할 것

다음 파일 또는 폴더가 있어야 합니다.

### 꼭 필요한 것

- FASTQ 파일이 들어 있는 폴더
  - 보통 `*_R1_001.fastq.gz`
  - 보통 `*_R2_001.fastq.gz`
- sequence xlsx 파일
  - sample ID
  - sequence
  - target window
  - 이런 정보가 들어 있어야 합니다.

### 있으면 좋은 것

- sample TALE xlsx 파일
  - sample ID와 Left/Right module 매핑
- TALE array xlsx 파일
  - Left/Right tail sequence 정보

이 두 파일이 없어도 핵심 분석은 가능할 수 있지만, tail mapping 관련 결과는 줄어들 수 있습니다.

### sequence xlsx 형식은 아무거나 써도 되나요?

아니요. `분석 원리` 자체는 하나의 고정 xlsx 형식만 강제하는 것은 아니지만, `현재 앱`은 읽을 수 있는 형식이 정해져 있습니다.

즉:

- 아무 xlsx나 자동으로 이해하는 구조는 아닙니다.
- 현재 앱이 읽을 수 있는 형식으로 정리되어 있어야 합니다.

### 기본 분석용 sequence xlsx 형식

기본 분석은 예전처럼 비교적 단순한 형식도 읽을 수 있습니다.

최소한 아래 정보가 있어야 합니다.

- sample ID 범위
- full sequence
- target window

예를 들면 아래와 비슷한 구조입니다.

```text
sample ID NO. | sequence | target window
71,72,75~85   | ...      | GCTCACGGTTATTTTGGCCGAT
86~90         | ...      | GGGCATTACTTGAATGCTACTGCGGGT
```

sample ID 칸에 짧은 설명이 붙어 있어도 기본 분석에서는 읽을 수 있습니다.

예:

```text
68(wild type)
68 (WT)
68-wt
```

이 경우 모두 sample `68` 로 해석됩니다.

오늘처럼 `seq정보_260315.xlsx` 처럼 sample `68` 하나만 들어 있는 flat xlsx는 heatmap용이 아니라 `기본 분석용`으로 사용하면 됩니다.

### heatmap 분석용 sequence xlsx 형식

heatmap 분석은 `block 구조`를 기대합니다.  
중요한 점은 `block이 여러 개여야 한다`가 아니라, `block 구조로 적혀 있어야 한다`는 것입니다.

즉 아래 정보가 block 단위로 있어야 합니다.

- block 이름 또는 구분 가능한 제목
- sample 범위
- full sequence
- target window
- 아래쪽에 row label과 sample ID 목록

예를 들면 아래처럼 이해하면 됩니다.

```text
[Block 1]
sample ID NO. | sequence | target window
49~67         | ...      | AAATGAATCTGCTAATGAA

row label | sample ID
R1L2      | 49
R1L3      | 50
...
Col0(WT)  | 67
```

이런 block이 하나만 있어도 heatmap 분석은 정상 동작합니다.  
즉 `N234` block 하나만 들어 있는 xlsx도 괜찮습니다.

반대로 현재 heatmap 분석에서 바로 읽지 못하는 경우는 다음과 같습니다.

- sample 범위, sequence, target window만 있고 row label/sample ID 목록이 없는 경우
- block 경계가 보이지 않아서 어떤 sample들이 한 heatmap row 집합인지 알 수 없는 경우

### 사용자가 새 heatmap용 xlsx를 만들 때 꼭 포함해야 할 것

새 xlsx를 직접 만들거나 정리해서 넣을 때는 아래를 넣으면 됩니다.

- block 이름
- sample 범위
- full sequence
- target window
- row label
- sample ID

선택 사항:

- desired product sequence

desired product sequence가 없어도 실행은 가능하지만, heatmap HTML 제목과 강조 정보가 더 단순하게 표시될 수 있습니다.

## 4. macOS에서 실행하는 방법

### 가장 쉬운 방법

1. GitHub에서 받은 ZIP 파일의 압축을 풉니다.
2. 압축을 푼 프로그램 폴더를 Finder에서 엽니다.
3. `run_maund_local_app.command` 파일을 더블클릭합니다.
4. macOS가 보안 경고를 띄우면 실행을 허용합니다.
5. 잠시 기다립니다.
6. 브라우저가 자동으로 열리면 바로 사용하면 됩니다.

### 만약 실행이 안 되면 먼저 확인할 것

- 내 Mac에 `Python 3`가 설치되어 있어야 합니다.
- `Python 3`가 없다면 먼저 설치한 뒤 다시 실행해야 합니다.
- 보안 경고 때문에 막히면:
  - Finder에서 `run_maund_local_app.command` 파일을 우클릭합니다.
  - `열기`를 누릅니다.
  - 다시 `열기`를 눌러 실행을 허용합니다.

### 자동으로 브라우저가 안 열릴 때

브라우저가 자동으로 열리지 않아도 당황하지 마세요. 아래 순서대로 하면 됩니다.

1. Chrome, Safari, Edge 중 아무 브라우저나 엽니다.
2. 브라우저 맨 위의 주소창을 한 번 클릭합니다.
3. 주소창에 들어 있는 기존 글자를 지웁니다.
4. 아래 주소를 그대로 복사합니다.

```text
http://127.0.0.1:8501
```

5. 방금 복사한 주소를 주소창에 붙여넣습니다.
6. 키보드에서 `Enter` 키를 누릅니다.
7. MAUND Local Web App 화면이 보이면 정상입니다.

### 터미널로 실행하는 방법

터미널을 사용할 줄 아는 사람은 아래처럼 실행해도 됩니다.

```bash
./run_maund_local_app.sh
```

## 5. Windows에서 실행하는 방법

1. GitHub에서 받은 ZIP 파일의 압축을 풉니다.
2. 압축을 푼 프로그램 폴더를 엽니다.
3. `run_maund_local_app.bat` 파일을 더블클릭합니다.
4. 검은 창이 열리면 닫지 말고 잠시 기다립니다.
5. 브라우저가 자동으로 열리면 그대로 사용합니다.

### 만약 실행이 안 되면 먼저 확인할 것

- Windows에 `Python 3`가 설치되어 있어야 합니다.
- Python 설치 시 `Add Python to PATH` 옵션을 켜 두는 것이 좋습니다.

### 자동으로 브라우저가 안 열릴 때

1. Chrome, Edge 중 아무 브라우저나 엽니다.
2. 브라우저 맨 위 주소창을 클릭합니다.
3. 아래 주소를 그대로 입력하거나 복사해서 붙여넣습니다.

```text
http://127.0.0.1:8501
```

4. `Enter` 키를 누릅니다.

## 6. 처음 실행할 때 무슨 일이 일어나는가

처음 실행할 때는 Python 3만 설치되어 있으면 됩니다.  
별도의 복잡한 설치 과정을 거치지 않도록 실행 방식을 단순화했습니다.

## 7. 실제 분석 화면 사용 방법

브라우저에 화면이 열리면, 아래 순서대로 하면 됩니다.

### STEP 1. 입력 파일 고르기

화면에는 여러 입력칸이 있습니다.  
각 입력칸 오른쪽에는 `선택` 버튼이 있습니다.

이 버튼을 누르면:

- macOS에서는 Finder 기반 선택창
- Windows에서는 파일 선택창

이 열립니다.

버튼을 누른 직후에는 브라우저 탭이 잠깐 로딩 상태로 보일 수 있습니다.  
이때는 정상입니다. 화면 뒤나 앞에 열린 선택창에서 폴더 또는 파일을 고른 뒤 `선택` 또는 `열기`를 누르면 원래 화면으로 돌아옵니다.

다음 항목을 차례대로 고르세요.

#### 1) FASTQ 폴더

- `FASTQ 폴더` 오른쪽의 `폴더 선택` 버튼을 누릅니다.
- FASTQ 파일들이 들어 있는 폴더를 선택합니다.
- 선택 후 `열기` 또는 `선택`을 누릅니다.

#### 2) Sequence xlsx

- `Sequence xlsx` 오른쪽의 `파일 선택` 버튼을 누릅니다.
- sequence 정보가 들어 있는 xlsx 파일을 선택합니다.

#### 3) Sample TALE xlsx

- 있으면 선택합니다.
- 없으면 비워 둘 수 있습니다.

#### 4) TALE array xlsx

- 있으면 선택합니다.
- 없으면 비워 둘 수 있습니다.

#### 5) 결과 저장 폴더

- 분석 결과가 저장될 상위 폴더를 선택합니다.
- 예를 들어 Desktop을 선택하면, 그 안에 `maund_<날짜>_<시간>` 폴더가 생깁니다.

### STEP 2. 분석 설정 입력하기

#### 0) 분석 모드 먼저 고르기

화면의 `분석 모드` 에서 아래 둘 중 하나를 선택합니다.

- `기본 분석`
- `heatmap 분석`

두 모드 차이는 다음과 같습니다.

##### 기본 분석

- 기존 방식입니다.
- `Target sequence` 를 직접 입력해야 합니다.
- 결과 HTML은 기존 haplotype 카드 중심으로 나옵니다.

##### heatmap 분석

- xlsx 안에 들어 있는 block을 자동으로 감지합니다.
- block은 1개만 있어도 됩니다.
- `Target sequence` 를 직접 입력하지 않습니다.
- block별로 결과 파일이 따로 만들어집니다.
- block별 HTML 안에 `기존 결과 + heatmap` 이 함께 보입니다.
- `입력 확인` 버튼을 먼저 눌러야 block 미리보기가 나타납니다.

#### 1) 분석할 샘플 번호

예시:

```text
71,72,75-85
```

의미:

- 71
- 72
- 75부터 85까지

를 분석하겠다는 뜻입니다.

비워두면 가능한 샘플을 자동으로 사용합니다.

#### 2) 제외할 샘플 번호

예시:

```text
73,74
```

의미:

- 73번 샘플 제외
- 74번 샘플 제외

#### 3) Target sequence

`기본 분석` 일 때만 사용하는 칸입니다.  
분석할 target sequence를 그대로 붙여넣습니다.

예시:

```text
AAATGAATCTGCTAATGAA
```

`heatmap 분석` 을 선택했을 때 이 칸이 비활성화되어 보이면 정상입니다.  
이 경우 target은 xlsx 안의 block 정보에서 자동으로 가져옵니다.

#### 4) Editor type

드롭다운에서 하나를 선택합니다.

- `TALED`
- `DdCBE`

각 editor type에 따라 허용 변이 규칙이 달라집니다.

## 8. 입력이 맞는지 먼저 확인하는 방법

1. `입력 확인` 버튼을 누릅니다.
2. 잠시 기다립니다.
3. 아래에 `입력 확인 결과`가 나타납니다.

여기서 다음을 볼 수 있습니다.

- 선택된 sample IDs
- FASTQ에 실제로 있는 sample IDs
- sequence xlsx에 실제로 있는 sample IDs
- 감지된 block 목록(heatmap 분석일 때)
- 오류 메시지
- 경고 메시지

### heatmap 분석에서 block 미리보기가 보이면 무엇을 해야 하나요?

`heatmap 분석` 을 선택한 뒤 `입력 확인` 을 누르면, 화면에 `블록 미리보기와 보완 입력` 영역이 나타날 수 있습니다.

이 영역에서는:

- 감지된 block 이름 확인
- sample 범위 확인
- target window 확인
- desired product sequence 확인
- block 이름 수정
- desired product sequence 추가 또는 수정

을 할 수 있습니다.

desired product sequence를 여러 개 적고 싶다면:

- 쉼표로 구분하거나
- 한 줄에 하나씩 적으면 됩니다.

예:

```text
AAATGAATCTGCTGATGAA
AAATGAATCTGCTAGTGAA
```

### 오류가 있으면 어떻게 하나요?

오류가 있으면 보통 아래 중 하나입니다.

- FASTQ 폴더를 잘못 선택함
- xlsx 파일을 잘못 선택함
- sample 번호를 잘못 입력함
- target sequence가 맞지 않음

이 경우:

1. 위 입력칸으로 다시 올라갑니다.
2. 잘못된 값을 수정합니다.
3. 다시 `입력 확인` 버튼을 누릅니다.

### 선택 버튼을 눌렀는데 아무 반응이 없는 것처럼 보이면?

아래 순서대로 확인하세요.

1. 브라우저 창 뒤에 Finder 또는 파일 선택창이 숨어 있지 않은지 확인합니다.
2. macOS라면 Dock에 있는 Finder 아이콘을 한 번 눌러 선택창이 떠 있는지 확인합니다.
3. 그래도 안 보이면 프로그램을 끄고 다시 실행한 뒤 다시 눌러봅니다.
4. 선택창 사용이 어렵다면, 입력칸에 폴더 경로나 파일 경로를 직접 붙여넣어도 됩니다.

## 9. 실제 분석 실행 방법

입력 확인에서 오류가 없으면:

1. `분석 실행` 버튼을 누릅니다.
2. 브라우저 탭을 바로 닫지 말고 기다립니다.
3. 분석이 끝나면 상태 메시지와 결과 영역이 나타납니다.

분석 시간은 데이터 크기에 따라 다릅니다.

## 10. 결과 확인 방법

분석이 끝나면 결과 영역에 여러 경로가 표시됩니다.

버튼도 함께 보일 수 있습니다.

### 결과 폴더 열기

- `결과 폴더 열기` 버튼을 누르면
- Finder 또는 파일 탐색기에서 결과 폴더가 열립니다.

### HTML 결과 열기

- `기본 분석` 일 때는 `HTML 결과 열기` 버튼이 보입니다.
- `heatmap 분석` 일 때는 `N234 HTML 열기`, `F260 HTML 열기` 처럼 block 이름이 들어간 버튼이 각각 보입니다.

이 버튼을 누르면 해당 block의 결과 HTML이 열립니다.

heatmap 분석의 block HTML 안에는 다음 내용이 한 번에 같이 들어 있습니다.

- block summary
- per-sample editing summary
- ranked editing table
- haplotype cards
- position heatmap

즉, 예를 들어 `N234 HTML` 을 열면 `N234의 기존 MAUND 결과` 와 `N234 heatmap` 을 한 화면에서 같이 볼 수 있습니다.

### 분석 메모 열기

- `분석 메모 열기` 버튼을 누르면
- `analysis_flow_<tag>.md` 파일을 바로 확인할 수 있습니다.

## 11. 프로그램을 끄는 방법

### macOS

터미널에서 실행 중이라면:

1. 터미널 창을 선택합니다.
2. 키보드에서 `Control + C` 를 누릅니다.

또는 아래 파일을 사용합니다.

```text
stop_maund_local_app.command
```

또는:

```bash
./stop_maund_local_app.sh
```

### Windows

프로그램을 실행했던 검은 창(Command Prompt)을 닫으면 됩니다.

## 12. heatmap 분석을 실제로 하는 순서

이 항목은 `N234`, `F260` 처럼 block 구조가 들어 있는 xlsx를 분석할 때를 기준으로 설명합니다. block은 1개만 있어도 됩니다.

1. 프로그램을 실행합니다.
2. `FASTQ 폴더` 를 선택합니다.
3. `Sequence xlsx` 를 선택합니다.
4. 필요하면 `Sample TALE xlsx`, `TALE array xlsx` 를 선택합니다.
5. `결과 저장 폴더` 를 선택합니다.
6. `분석 모드` 에서 `heatmap 분석` 을 고릅니다.
7. `Heatmap 색상 범위` 에서 원하는 값을 고릅니다.
8. 필요한 경우 `분석할 샘플 번호` 또는 `제외할 샘플 번호` 를 입력합니다.
9. `입력 확인` 버튼을 누릅니다.
10. 화면 아래 `블록 미리보기와 보완 입력` 영역이 나타나는지 확인합니다.
11. block 이름 또는 desired product sequence를 바꾸고 싶으면 여기서 수정합니다.
12. `분석 실행` 버튼을 누릅니다.
13. 완료되면 `결과 폴더 열기` 또는 block별 `HTML 열기` 버튼을 누릅니다.

heatmap 읽는 방법:

- 세로축 행: sample 또는 TALE 조합
- 가로축 열: target window의 각 위치
- 셀 숫자: 해당 위치의 intended conversion frequency(%)
- 색상: 화면에서 고른 범위를 사용합니다. `0-1` 을 고르면 아주 작은 차이도 강하게 보이고, `0-5` 를 고르면 낮은 편집율 차이가 잘 보이며, `0-100` 을 고르면 논문 그림처럼 넓은 범위 기준으로 보입니다.
- 오른쪽 범례: 현재 선택한 색상 범위가 함께 표시되어, 어떤 색이 어느 % 범위를 뜻하는지 바로 볼 수 있습니다.
- 원하는 위치는 heatmap에서 더 눈에 띄게 표시됩니다.

## 13. 실행 파일로 묶고 싶을 때

### macOS

```bash
./scripts/build_macos_app.sh
```

### Windows PowerShell

```powershell
./scripts/build_windows_app.ps1
```

## 14. 테스트

개발자가 확인할 때는 아래를 사용합니다.

```bash
python3 -m unittest tests.test_engine tests.test_web_app tests.test_version
```

## 15. GitHub에 처음 올리는 방법

이 부분은 `저장소 관리자` 만 하면 됩니다. 일반 사용자는 하지 않아도 됩니다.

### 1) GitHub CLI 설치

macOS에서는 Homebrew가 있다면 아래처럼 설치할 수 있습니다.

```bash
brew install gh
```

### 2) GitHub 로그인

아래 명령을 실행한 뒤 브라우저에서 로그인과 승인을 완료합니다.

```bash
gh auth login --hostname github.com --git-protocol https --web
```

### 3) 저장소 생성과 첫 푸시

기본 저장소 이름은 `maund-local-webapp` 입니다.

```bash
./scripts/publish_github.sh martinyblue maund-local-webapp
```

이 명령은 다음을 한 번에 처리합니다.

- `martinyblue/maund-local-webapp` 저장소가 없으면 새로 만듭니다.
- 이미 있으면 기존 저장소에 최신 커밋을 푸시합니다.
- 원격 주소 `origin` 을 해당 GitHub 저장소로 맞춥니다.
- `VERSION` 파일에 적힌 값을 읽어 `v버전번호` 태그를 만듭니다.
- GitHub Release 가 없으면 같은 버전으로 Release 도 만듭니다.

### 4) 다른 사람이 다운로드할 때 알려줄 주소

푸시가 끝나면 아래 주소를 다른 사람에게 전달하면 됩니다.

```text
https://github.com/martinyblue/maund-local-webapp
```

### 5) 다음 업데이트를 버전으로 올리는 방법

예를 들어 다음 버전을 `0.1.1` 로 올리고 싶다면:

```bash
./scripts/bump_version.sh 0.1.1
```

그 다음 아래 순서로 진행합니다.

1. `CHANGELOG.md` 에 자동으로 추가된 새 버전 섹션의 내용을 수정합니다.
2. 코드 변경을 커밋합니다.
3. 아래 명령으로 GitHub에 올립니다.

```bash
./scripts/publish_github.sh martinyblue maund-local-webapp
```

그러면 GitHub에 `v0.1.1` 같은 새 태그와 Release 가 생기고, 사용자는 그 버전을 기준으로 다운로드할 수 있습니다.

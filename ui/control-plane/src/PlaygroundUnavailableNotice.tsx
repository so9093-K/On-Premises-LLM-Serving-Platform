import { Alert } from '@patternfly/react-core';
import { Link } from 'react-router-dom';

// 배포가 제공하지 않는 Playground 작업 화면의 안내 문구는 여기 한 곳이 소유한다.
// 제공 여부는 bootstrap features가 결정하며, 이 안내는 공개 API 요청을 보내지 않는다는 사실만 알린다.
export function PlaygroundUnavailableNotice({ label, preview = false }: { label: string; preview?: boolean }) {
  return (
    <Alert isInline variant="info" title={`현재 배포 환경에서는 ${label} 기능을 제공하지 않습니다.`}>
      <p>
        {preview ? '화면 구성과 입력 방식은 확인할 수 있지만 요청은 보내지 않습니다.' : '이 화면에서는 요청을 보내지 않습니다.'}
        {' '}장애가 아니라 배포 구성에 따른 범위입니다.
      </p>
      <p>
        사용하려면 서버 운영자가 이 기능을 제공하는 배포 환경을 구성해야 합니다.
        {' '}<Link to="/">운영 개요에서 현재 지원 기능 보기 →</Link>
      </p>
    </Alert>
  );
}

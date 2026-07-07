import React, { useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Spinner,
  Text,
  Title1,
  makeStyles,
  tokens
} from '@fluentui/react-components';
import {
  DismissRegular,
  MaximizeRegular,
  SubtractRegular,
  ArrowClockwiseRegular
} from '@fluentui/react-icons';
import { useQuery } from '@tanstack/react-query';
import { Virtuoso } from 'react-virtuoso';
import { normalizeOperatorView } from './contract.js';

const views = ['总览', '任务', '窗口', '网络', '设置'];

const useStyles = makeStyles({
  app: {
    width: '100vw',
    height: '100vh',
    overflow: 'hidden',
    backgroundColor: '#eef2f5',
    color: tokens.colorNeutralForeground1,
    display: 'grid',
    gridTemplateRows: '54px 1fr'
  },
  titlebar: {
    WebkitAppRegion: 'drag',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingLeft: '16px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: 'rgba(248, 251, 252, 0.94)'
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px'
  },
  mark: {
    width: '24px',
    height: '24px',
    borderRadius: '8px',
    background: 'linear-gradient(145deg, #2f6de0, #2f8f74)'
  },
  windowActions: {
    WebkitAppRegion: 'no-drag',
    height: '100%',
    display: 'flex'
  },
  chromeButton: {
    width: '52px',
    height: '100%',
    borderRadius: 0
  },
  stage: {
    minHeight: 0,
    display: 'grid',
    gridTemplateColumns: '214px minmax(0, 1fr)',
    gap: '16px',
    padding: '20px'
  },
  nav: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: 'auto 1fr auto',
    padding: '14px 10px',
    borderRadius: '10px',
    backgroundColor: 'rgba(255, 255, 255, 0.82)',
    boxShadow: '0 12px 28px rgba(41, 56, 69, 0.12)'
  },
  navList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px'
  },
  navButton: {
    justifyContent: 'flex-start',
    height: '40px'
  },
  content: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: '116px 1fr',
    gap: '12px'
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 18px',
    borderRadius: '10px',
    backgroundColor: 'rgba(255,255,255,0.86)',
    boxShadow: '0 12px 28px rgba(41, 56, 69, 0.12)'
  },
  taskPanel: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: 'auto minmax(0, 1fr) auto',
    gap: '10px'
  },
  intentCard: {
    padding: '18px'
  },
  eventCard: {
    minHeight: 0,
    padding: '0',
    overflow: 'hidden'
  },
  eventHeader: {
    padding: '14px 18px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`
  },
  eventItem: {
    margin: '10px 14px',
    padding: '12px 14px',
    borderRadius: '10px',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1
  },
  eventMeta: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '12px',
    marginBottom: '7px'
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: '36px',
    color: tokens.colorNeutralForeground3
  },
  note: {
    padding: '10px',
    borderRadius: '8px',
    backgroundColor: 'rgba(255,255,255,0.68)'
  }
});

async function readStatus() {
  const payload = await window.xinaoStatus.read();
  return normalizeOperatorView(payload);
}

export function App() {
  const styles = useStyles();
  const [activeView, setActiveView] = useState('任务');
  const statusQuery = useQuery({
    queryKey: ['operator-view'],
    queryFn: readStatus
  });

  const payload = statusQuery.data;
  const events = useMemo(() => payload?.ui?.events || [], [payload]);
  const sourceLabel = payload?.source === 'operator_endpoint' ? '当前运行态' : '当前运行态';

  return (
    <div className={styles.app}>
      <header className={styles.titlebar}>
        <div className={styles.brand}>
          <div className={styles.mark} aria-hidden="true" />
          <div>
            <Text weight="semibold">XINAO Surface</Text>
            <br />
            <Text size={200} color="secondary">只读状态盘</Text>
          </div>
        </div>
        <div className={styles.windowActions}>
          <Button className={styles.chromeButton} appearance="subtle" icon={<SubtractRegular />} aria-label="最小化" onClick={() => window.xinaoWindow.minimize()} />
          <Button className={styles.chromeButton} appearance="subtle" icon={<MaximizeRegular />} aria-label="最大化" onClick={() => window.xinaoWindow.toggleMaximize()} />
          <Button className={styles.chromeButton} appearance="subtle" icon={<DismissRegular />} aria-label="关闭" onClick={() => window.xinaoWindow.close()} />
        </div>
      </header>

      <main className={styles.stage}>
        <aside className={styles.nav}>
          <Text size={200} weight="semibold" color="secondary">本地状态盘</Text>
          <nav className={styles.navList}>
            {views.map((view) => (
              <Button
                key={view}
                className={styles.navButton}
                appearance={activeView === view ? 'primary' : 'subtle'}
                onClick={() => setActiveView(view)}
              >
                {view}
              </Button>
            ))}
          </nav>
          <div className={styles.note}>
            <Text size={200}>成熟 Activity Feed</Text>
            <br />
            <Text size={200} color="secondary">当前事务 / 事件流</Text>
          </div>
        </aside>

        <section className={styles.content}>
          <div className={styles.header}>
            <div>
              <Text size={200} weight="semibold" color="success">TASK</Text>
              <Title1 block>{activeView}</Title1>
              <Text color="secondary">上面是当前任务总意图，下面是事件流。</Text>
            </div>
            <Badge appearance="tint" color={statusQuery.isFetching ? 'brand' : 'success'}>
              {statusQuery.isLoading ? '读取中' : sourceLabel}
            </Badge>
          </div>

          {activeView === '任务' ? (
            <TaskView
              styles={styles}
              payload={payload}
              events={events}
              isLoading={statusQuery.isLoading}
              isFetching={statusQuery.isFetching}
              refetch={() => statusQuery.refetch()}
            />
          ) : (
            <Card>
              <CardHeader header={<Text weight="semibold">{activeView}</Text>} />
              <Text color="secondary">二级页面保留入口；默认工作面只固定当前任务和事件流。</Text>
            </Card>
          )}
        </section>
      </main>
    </div>
  );
}

function TaskView({ styles, payload, events, isLoading, isFetching, refetch }) {
  const ui = payload?.ui;
  return (
    <div className={styles.taskPanel}>
      <Card className={styles.intentCard}>
        <CardHeader
          header={<Text size={200} weight="semibold" color="secondary">当前任务总意图</Text>}
          description={<Text color="secondary">{ui?.status || '读取中'}</Text>}
        />
        <Title1>{ui?.headline || '读取中'}</Title1>
        <Text block>{ui?.transaction || '等待本地接口返回当前事务'}</Text>
        <Text block color="secondary">用户是否需要处理：{ui?.needsUser || '否'}</Text>
      </Card>

      <Card className={styles.eventCard}>
        <div className={styles.eventHeader}>
          <Text weight="semibold">事件流</Text>
          {isLoading ? <Spinner size="tiny" /> : null}
        </div>
        <Virtuoso
          data={events}
          itemContent={(_, item) => (
            <article className={styles.eventItem}>
              <div className={styles.eventMeta}>
                <Text size={200} color="secondary">{item.at}</Text>
                <Badge appearance="outline">{item.phase}</Badge>
              </div>
              <Text block>{item.conclusion}</Text>
              <Text block size={200} color="secondary">{item.impact}</Text>
            </article>
          )}
        />
      </Card>

      <footer className={styles.footer}>
        <Text size={200}>{payload?.reason || 'OperatorViewPayload v1'}</Text>
        <Button icon={<ArrowClockwiseRegular />} onClick={refetch} disabled={isFetching}>
          刷新
        </Button>
      </footer>
    </div>
  );
}

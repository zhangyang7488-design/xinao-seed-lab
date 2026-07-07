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

const views = ['任务', '总览', '窗口', '网络', '设置'];

const useStyles = makeStyles({
  app: {
    width: '100vw',
    height: '100vh',
    overflow: 'hidden',
    backgroundColor: '#eef2f0',
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
    backgroundColor: 'rgba(248, 251, 250, 0.96)'
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    minWidth: 0
  },
  mark: {
    width: '24px',
    height: '24px',
    borderRadius: '6px',
    background: 'linear-gradient(145deg, #2f6de0, #2f8f74)'
  },
  titleActions: {
    WebkitAppRegion: 'no-drag',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    height: '100%'
  },
  windowActions: {
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
    padding: '18px'
  },
  nav: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: 'auto auto 1fr auto',
    gap: '12px',
    padding: '14px 10px',
    borderRadius: '8px',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: 'rgba(255, 255, 255, 0.84)',
    boxShadow: '0 10px 24px rgba(42, 56, 61, 0.10)'
  },
  navList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px'
  },
  navButton: {
    justifyContent: 'flex-start',
    height: '40px',
    borderRadius: '6px'
  },
  navNote: {
    alignSelf: 'end',
    padding: '10px',
    borderRadius: '6px',
    backgroundColor: 'rgba(238, 242, 240, 0.88)'
  },
  content: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: 'auto minmax(0, 1fr) 34px',
    gap: '12px'
  },
  taskBand: {
    minHeight: 0,
    display: 'grid',
    gap: '8px',
    padding: '4px 2px 12px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: 'transparent'
  },
  taskKicker: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    minWidth: 0
  },
  headline: {
    margin: 0,
    overflowWrap: 'anywhere'
  },
  taskText: {
    maxWidth: '980px',
    overflowWrap: 'anywhere'
  },
  statusRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px'
  },
  feedCard: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: '56px minmax(0, 1fr)',
    padding: 0,
    overflow: 'hidden',
    borderRadius: '8px',
    border: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: '0 10px 24px rgba(42, 56, 61, 0.10)'
  },
  feedHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '12px 18px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: 'rgba(249, 250, 250, 0.94)'
  },
  feedTitle: {
    minWidth: 0,
    display: 'grid',
    gap: '2px'
  },
  feedActions: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px'
  },
  eventItem: {
    display: 'grid',
    gridTemplateColumns: '128px minmax(0, 1fr)',
    gap: '14px',
    padding: '13px 18px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1
  },
  eventTime: {
    paddingTop: '3px',
    color: tokens.colorNeutralForeground3,
    fontVariantNumeric: 'tabular-nums',
    overflowWrap: 'anywhere'
  },
  eventBody: {
    minWidth: 0,
    display: 'grid',
    gap: '6px'
  },
  eventTop: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px'
  },
  eventDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    backgroundColor: '#2f8f74',
    boxShadow: '0 0 0 4px rgba(47, 143, 116, 0.12)'
  },
  eventText: {
    overflowWrap: 'anywhere'
  },
  emptyFeed: {
    display: 'grid',
    placeItems: 'center',
    color: tokens.colorNeutralForeground3
  },
  secondaryPage: {
    minHeight: 0,
    display: 'grid',
    gridTemplateRows: 'auto minmax(0, 1fr)',
    gap: '12px'
  },
  pageHeader: {
    display: 'grid',
    gap: '4px',
    padding: '4px 2px 12px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`
  },
  overviewGrid: {
    minHeight: 0,
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) minmax(260px, 360px)',
    gap: '12px'
  },
  overviewCard: {
    minHeight: 0,
    padding: '16px',
    borderRadius: '8px'
  },
  previewList: {
    minHeight: 0,
    overflow: 'hidden',
    display: 'grid',
    gap: '10px'
  },
  previewItem: {
    paddingBottom: '10px',
    borderBottom: `1px solid ${tokens.colorNeutralStroke2}`
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    minHeight: '34px',
    color: tokens.colorNeutralForeground3
  },
  footerText: {
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap'
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
  const ui = payload?.ui;
  const events = useMemo(() => payload?.ui?.events || [], [payload]);
  const sourceLabel = payload?.source === 'operator_endpoint' ? '当前运行态' : '本地运行态';
  const fetchingLabel = statusQuery.isLoading ? '读取中' : sourceLabel;

  return (
    <div className={styles.app}>
      <header className={styles.titlebar}>
        <div className={styles.brand}>
          <div className={styles.mark} aria-hidden="true" />
          <div>
            <Text weight="semibold">XINAO Surface</Text>
            <br />
            <Text size={200} color="secondary">Mission Control Lite</Text>
          </div>
        </div>

        <div className={styles.titleActions}>
          <Badge appearance="tint" color={statusQuery.isFetching ? 'brand' : 'success'}>
            {fetchingLabel}
          </Badge>
          <Button
            appearance="subtle"
            icon={<ArrowClockwiseRegular />}
            aria-label="刷新事件流"
            onClick={() => statusQuery.refetch()}
            disabled={statusQuery.isFetching}
          />
          <div className={styles.windowActions}>
            <Button className={styles.chromeButton} appearance="subtle" icon={<SubtractRegular />} aria-label="最小化" onClick={() => window.xinaoWindow.minimize()} />
            <Button className={styles.chromeButton} appearance="subtle" icon={<MaximizeRegular />} aria-label="最大化" onClick={() => window.xinaoWindow.toggleMaximize()} />
            <Button className={styles.chromeButton} appearance="subtle" icon={<DismissRegular />} aria-label="关闭" onClick={() => window.xinaoWindow.close()} />
          </div>
        </div>
      </header>

      <main className={styles.stage}>
        <aside className={styles.nav}>
          <Text size={200} weight="semibold" color="secondary">本地状态盘</Text>
          <Badge appearance="outline">左侧模式</Badge>
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
          <div className={styles.navNote}>
            <Text size={200}>默认工作面：任务</Text>
            <br />
            <Text size={200} color="secondary">预览只在总览二级页。</Text>
          </div>
        </aside>

        <section className={styles.content}>
          {activeView === '任务' ? (
            <TaskWorkspace styles={styles} ui={ui} events={events} isLoading={statusQuery.isLoading} />
          ) : activeView === '总览' ? (
            <OverviewPreview styles={styles} ui={ui} events={events} />
          ) : (
            <SecondaryPage styles={styles} title={activeView} />
          )}

          <footer className={styles.footer}>
            <Text size={200} className={styles.footerText}>{payload?.reason || 'OperatorViewPayload v1'}</Text>
            <Text size={200}>最后读取：{payload?.generated_at || '等待刷新'}</Text>
          </footer>
        </section>
      </main>
    </div>
  );
}

function TaskWorkspace({ styles, ui, events, isLoading }) {
  return (
    <>
      <section className={styles.taskBand}>
        <div className={styles.taskKicker}>
          <Badge appearance="filled" color="brand">当前任务</Badge>
          <Text size={200} color="secondary">{ui?.status || '等待本地接口返回'}</Text>
        </div>
        <Title1 block className={styles.headline}>{ui?.headline || '读取中'}</Title1>
        <Text block className={styles.taskText}>{ui?.intent || '等待本地接口返回当前意图'}</Text>
        <Text block color="secondary" className={styles.taskText}>{ui?.transaction || '等待本地接口返回当前事务'}</Text>
        <div className={styles.statusRow}>
          <Badge appearance="outline">用户处理：{ui?.needsUser || '否'}</Badge>
          <Badge appearance="tint" color="success">自动刷新</Badge>
        </div>
      </section>

      <LiveFeed styles={styles} events={events} isLoading={isLoading} />
    </>
  );
}

function OverviewPreview({ styles, ui, events }) {
  const previewEvents = events.slice(0, 4);
  return (
    <section className={styles.secondaryPage}>
      <div className={styles.pageHeader}>
        <Badge appearance="outline">二级窗口</Badge>
        <Title1 block className={styles.headline}>总览预览</Title1>
        <Text color="secondary">这里只做预览；默认执行工作面仍在左侧“任务”。</Text>
      </div>

      <div className={styles.overviewGrid}>
        <Card className={styles.overviewCard}>
          <CardHeader
            header={<Text weight="semibold">当前任务预览</Text>}
            description={<Text color="secondary">{ui?.status || '等待本地接口返回'}</Text>}
          />
          <Title1 className={styles.headline}>{ui?.headline || '读取中'}</Title1>
          <Text block className={styles.taskText}>{ui?.transaction || '等待当前事务'}</Text>
          <Text block color="secondary">用户处理：{ui?.needsUser || '否'}</Text>
        </Card>

        <Card className={styles.overviewCard}>
          <CardHeader header={<Text weight="semibold">事件预览</Text>} />
          <div className={styles.previewList}>
            {previewEvents.map((item) => (
              <div key={`${item.at}-${item.phase}-${item.conclusion}`} className={styles.previewItem}>
                <Text size={200} color="secondary">{item.at}</Text>
                <br />
                <Badge appearance="outline">{item.phase}</Badge>
                <Text block weight="semibold" className={styles.eventText}>{item.conclusion}</Text>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </section>
  );
}

function SecondaryPage({ styles, title }) {
  return (
    <section className={styles.secondaryPage}>
      <div className={styles.pageHeader}>
        <Badge appearance="outline">二级入口</Badge>
        <Title1 block>{title}</Title1>
        <Text color="secondary">入口保留；不替代默认任务工作面。</Text>
      </div>
      <Card className={styles.overviewCard}>
        <Text color="secondary">{title} 页面保留为二级入口。</Text>
      </Card>
    </section>
  );
}

function LiveFeed({ styles, events, isLoading }) {
  return (
    <Card className={styles.feedCard}>
      <div className={styles.feedHeader}>
        <div className={styles.feedTitle}>
          <Text weight="semibold">Live Execution Feed</Text>
          <Text size={200} color="secondary">按时间刷新后台执行轨迹，不展示原始日志墙。</Text>
        </div>
        <div className={styles.feedActions}>
          {isLoading ? <Spinner size="tiny" /> : null}
          <Badge appearance="outline">{events.length} 条</Badge>
        </div>
      </div>

      {events.length > 0 ? (
        <Virtuoso
          data={events}
          style={{ height: '100%' }}
          itemContent={(_, item) => <EventRow item={item} styles={styles} />}
        />
      ) : (
        <div className={styles.emptyFeed}>
          <Text>等待第一条执行事件。</Text>
        </div>
      )}
    </Card>
  );
}

function EventRow({ item, styles }) {
  return (
    <article className={styles.eventItem}>
      <Text size={200} className={styles.eventTime}>{item.at}</Text>
      <div className={styles.eventBody}>
        <div className={styles.eventTop}>
          <span className={styles.eventDot} aria-hidden="true" />
          <Badge appearance="outline">{item.phase}</Badge>
        </div>
        <Text block weight="semibold" className={styles.eventText}>{item.conclusion}</Text>
        <Text block size={200} color="secondary" className={styles.eventText}>{item.impact}</Text>
      </div>
    </article>
  );
}

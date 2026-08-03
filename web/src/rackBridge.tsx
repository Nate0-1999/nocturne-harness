import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import {
  RackApiProvider,
  createHostPluginApi,
  isRackModuleId,
  rackSelectionsEqual,
  type RackAction,
  type RackActionResult,
  type RackModuleId,
  type RackModuleManifest,
  type RackPluginApi,
  type RackQueryRequest,
  type RackQueryResult,
  type RackSelection,
  type RackSnapshot,
} from './rack'
import type { RackEnvelopeEvent, RackResizeEvent } from './rackEvents'

const BRIDGE_VERSION = 1
const READY_MESSAGE = 'nocturne.rack.ready'
const CONNECT_MESSAGE = 'nocturne.rack.connect'

type HostMessage =
  | { type: 'snapshot'; snapshot: RackSnapshot }
  | { type: 'envelope'; event: RackEnvelopeEvent }
  | { type: 'resize'; event: RackResizeEvent }
  | { type: 'selection'; selection: RackSelection }
  | { type: 'response'; request_id: string; result: unknown }
  | { type: 'error'; request_id: string; error: string }

type RemoteMessage =
  | { type: 'dispatch'; request_id: string; action: RackAction }
  | { type: 'query'; request_id: string; request: RackQueryRequest }
  | { type: 'selection'; selection: RackSelection }

type RemoteRequestPayload =
  | { type: 'dispatch'; action: RackAction }
  | { type: 'query'; request: RackQueryRequest }

interface ConnectMessage {
  type: typeof CONNECT_MESSAGE
  version: typeof BRIDGE_VERSION
  manifest: RackModuleManifest
  snapshot: RackSnapshot
  selection: RackSelection
  regression_fixture: 'M2C REGRESSION' | null
}

export function RackPluginIframe({
  manifest,
  isRegressionFixture = false,
}: {
  manifest: RackModuleManifest
  isRegressionFixture?: boolean
}) {
  const frameRef = useRef<HTMLIFrameElement>(null)
  const api = useMemo(() => createHostPluginApi(manifest), [manifest])
  const frameOrigin = useMemo(() => rackFrameOrigin(), [])

  useEffect(() => {
    let port: MessagePort | null = null
    let unsubscribe: (() => void)[] = []

    const closeBridge = () => {
      for (const stop of unsubscribe) {
        stop()
      }
      unsubscribe = []
      port?.close()
      port = null
    }

    const connect = () => {
      const target = frameRef.current?.contentWindow
      if (target === null || target === undefined) {
        return
      }
      closeBridge()
      const channel = new MessageChannel()
      port = channel.port1
      port.onmessage = (event: MessageEvent<RemoteMessage>) => {
        const message = event.data
        if (!isRecord(message) || typeof message.type !== 'string') {
          return
        }
        if (message.type === 'dispatch' && typeof message.request_id === 'string') {
          void api.events
            .dispatch(message.action)
            .then((result) => send({
              type: 'response',
              request_id: message.request_id,
              result,
            }))
            .catch((error: unknown) => sendError(message.request_id, error))
          return
        }
        if (message.type === 'query' && typeof message.request_id === 'string') {
          void api.query
            .query(message.request)
            .then((result) => send({
              type: 'response',
              request_id: message.request_id,
              result,
            }))
            .catch((error: unknown) => sendError(message.request_id, error))
          return
        }
        if (message.type === 'selection' && isRackSelection(message.selection)) {
          api.selection.select(message.selection)
        }
      }
      port.start()

      unsubscribe = [
        api.events.subscribeState(() => {
          send({ type: 'snapshot', snapshot: api.events.getSnapshot() })
        }),
        api.events.subscribe((event) => send({ type: 'envelope', event })),
        api.events.subscribeResize((event) => send({ type: 'resize', event })),
        api.selection.subscribe(() => {
          send({ type: 'selection', selection: api.selection.getSnapshot() })
        }),
      ]

      const message: ConnectMessage = {
        type: CONNECT_MESSAGE,
        version: BRIDGE_VERSION,
        manifest,
        snapshot: api.events.getSnapshot(),
        selection: api.selection.getSnapshot(),
        regression_fixture: isRegressionFixture ? 'M2C REGRESSION' : null,
      }
      target.postMessage(message, frameOrigin, [channel.port2])
    }

    const send = (message: HostMessage) => {
      port?.postMessage(message)
    }

    const sendError = (requestId: string, error: unknown) => {
      send({
        type: 'error',
        request_id: requestId,
        error: error instanceof Error ? error.message : 'Rack bridge request failed',
      })
    }

    const onWindowMessage = (event: MessageEvent) => {
      const target = frameRef.current?.contentWindow
      if (
        event.source !== target ||
        event.origin !== frameOrigin ||
        !isRecord(event.data)
      ) {
        return
      }
      if (
        event.data.type === READY_MESSAGE &&
        event.data.version === BRIDGE_VERSION &&
        event.data.module_id === manifest.id
      ) {
        connect()
      }
    }

    globalThis.addEventListener('message', onWindowMessage)
    return () => {
      globalThis.removeEventListener('message', onWindowMessage)
      closeBridge()
    }
  }, [api, frameOrigin, isRegressionFixture, manifest])

  return (
    <iframe
      ref={frameRef}
      className="rack-plugin-frame"
      data-testid={`rack-plugin-frame-${manifest.id}`}
      title={manifest.name}
      sandbox="allow-scripts allow-same-origin"
      src={rackFrameUrl(manifest.id)}
    />
  )
}

function rackFrameUrl(moduleId: RackModuleId): string {
  const url = new URL(globalThis.location.href)
  url.hostname = 'rack.localhost'
  url.pathname = '/'
  url.search = ''
  url.searchParams.set('rack_module', moduleId)
  url.searchParams.set('rack_host', globalThis.location.origin)
  url.hash = ''
  return url.toString()
}

function rackFrameOrigin(): string {
  const url = new URL(globalThis.location.href)
  url.hostname = 'rack.localhost'
  return url.origin
}

export function RackRemoteProvider({
  moduleId,
  children,
  regressionFixtureMarker,
}: {
  moduleId: RackModuleId
  children: ReactNode
  regressionFixtureMarker?: ReactNode
}) {
  const [api, setApi] = useState<RackPluginApi | null>(null)
  const [isRegressionFixture, setIsRegressionFixture] = useState(false)
  const hostOrigin = remoteHostOrigin()

  useEffect(() => {
    let activePort: MessagePort | null = null

    const onConnect = (event: MessageEvent<ConnectMessage>) => {
      const message = event.data
      const transferredPort = event.ports[0]
      if (
        event.source !== globalThis.parent ||
        event.origin !== hostOrigin ||
        !isRecord(message) ||
        message.type !== CONNECT_MESSAGE ||
        message.version !== BRIDGE_VERSION ||
        message.manifest?.id !== moduleId ||
        transferredPort === undefined
      ) {
        return
      }
      activePort?.close()
      activePort = transferredPort
      setApi(createRemoteApi(message, transferredPort))
      setIsRegressionFixture(message.regression_fixture === 'M2C REGRESSION')
    }

    globalThis.addEventListener('message', onConnect)
    globalThis.parent.postMessage(
      { type: READY_MESSAGE, version: BRIDGE_VERSION, module_id: moduleId },
      hostOrigin,
    )
    return () => {
      globalThis.removeEventListener('message', onConnect)
      activePort?.close()
    }
  }, [hostOrigin, moduleId])

  if (api === null) {
    return (
      <div className="rack-remote-loading" role="status">
        Linking {moduleId} module…
      </div>
    )
  }
  return (
    <RackApiProvider api={api}>
      {children}
      {isRegressionFixture ? regressionFixtureMarker : null}
    </RackApiProvider>
  )
}

function remoteHostOrigin(): string {
  const origin = new URL(globalThis.location.href).searchParams.get('rack_host')
  if (
    origin === null ||
    !/^http:\/\/(?:localhost|127\.0\.0\.1):\d+$/.test(origin)
  ) {
    throw new Error('rack frame did not receive a valid local host origin')
  }
  return origin
}

function createRemoteApi(
  connection: ConnectMessage,
  port: MessagePort,
): RackPluginApi {
  let snapshot = connection.snapshot
  let selection = connection.selection
  let nextRequest = 0
  const stateListeners = new Set<() => void>()
  const envelopeListeners = new Set<(event: RackEnvelopeEvent) => void>()
  const resizeListeners = new Set<(event: RackResizeEvent) => void>()
  const selectionListeners = new Set<() => void>()
  const pending = new Map<
    string,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >()

  const request = <Result,>(
    message: RemoteRequestPayload,
  ): Promise<Result> => {
    const requestId = `${connection.manifest.id}:${++nextRequest}`
    return new Promise<Result>((resolve, reject) => {
      pending.set(requestId, {
        resolve: (value) => resolve(value as Result),
        reject,
      })
      port.postMessage({ ...message, request_id: requestId })
    })
  }

  port.onmessage = (event: MessageEvent<HostMessage>) => {
    const message = event.data
    if (!isRecord(message) || typeof message.type !== 'string') {
      return
    }
    if (message.type === 'snapshot') {
      snapshot = message.snapshot
      notify(stateListeners)
    } else if (message.type === 'envelope') {
      for (const listener of envelopeListeners) {
        listener(message.event)
      }
    } else if (message.type === 'resize') {
      for (const listener of resizeListeners) {
        listener(message.event)
      }
    } else if (message.type === 'selection') {
      selection = message.selection
      notify(selectionListeners)
    } else if (message.type === 'response' || message.type === 'error') {
      const waiting = pending.get(message.request_id)
      if (waiting === undefined) {
        return
      }
      pending.delete(message.request_id)
      if (message.type === 'error') {
        waiting.reject(new Error(message.error))
      } else {
        waiting.resolve(message.result)
      }
    }
  }
  port.start()

  return {
    manifest: connection.manifest,
    events: {
      getSnapshot: () => snapshot,
      subscribeState(listener) {
        stateListeners.add(listener)
        return () => stateListeners.delete(listener)
      },
      subscribe(listener) {
        envelopeListeners.add(listener)
        return () => envelopeListeners.delete(listener)
      },
      subscribeResize(listener) {
        resizeListeners.add(listener)
        return () => resizeListeners.delete(listener)
      },
      dispatch<Action extends RackAction>(action: Action) {
        return request<RackActionResult<Action>>({ type: 'dispatch', action })
      },
    },
    query: {
      query(queryRequest) {
        return request<RackQueryResult>({ type: 'query', request: queryRequest })
      },
    },
    selection: {
      getSnapshot: () => selection,
      subscribe(listener) {
        selectionListeners.add(listener)
        return () => selectionListeners.delete(listener)
      },
      select(nextSelection) {
        if (rackSelectionsEqual(nextSelection, selection)) {
          return
        }
        selection = nextSelection
        notify(selectionListeners)
        port.postMessage({ type: 'selection', selection: nextSelection } satisfies RemoteMessage)
      },
    },
  }
}

function isRackSelection(value: unknown): value is RackSelection {
  if (value === null) {
    return true
  }
  if (!isRecord(value) || typeof value.id !== 'string') {
    return false
  }
  if (value.kind === 'thread' || value.kind === 'memory') {
    return true
  }
  if (value.kind === 'spend_lane') {
    return value.as_of === null || typeof value.as_of === 'string'
  }
  return value.kind === 'module' && isRackModuleId(value.id)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function notify(listeners: Set<() => void>): void {
  for (const listener of listeners) {
    listener()
  }
}

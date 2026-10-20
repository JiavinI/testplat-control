import { Descriptions } from 'antd'
import { JsonBlock } from './JsonBlock'
import { scenarioConfiguration } from './scenarioDisplay'
import type { ScenarioStepDefinition } from './types'

export function ScenarioConfiguration({ step }: { step: ScenarioStepDefinition }) {
  const entries = Object.entries(scenarioConfiguration(step))
  if (!entries.length) return null
  return <Descriptions size="small" column={1} items={entries.map(([key, value]) => ({
    key, label: key, children: <JsonBlock value={value} />,
  }))} />
}

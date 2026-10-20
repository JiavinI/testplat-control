import { Collapse, Typography } from 'antd'
import { ScenarioConfiguration } from './ScenarioConfiguration'
import { scenarioTypeLabel } from './scenarioDisplay'
import { JsonBlock } from './JsonBlock'
import type { ScenarioDefinition } from './types'

/** Engine 已校验的调用绑定；此处只展示引用，不维护参数副本。 */
export function ScenarioBindings({ definition }: { definition: ScenarioDefinition }) {
  return <Collapse size="small" items={definition.steps.map((step) => ({
    key: step.step_id,
    label: `${step.name ?? step.step_id} · ${scenarioTypeLabel(step.type)}`,
    children: <>
      <Typography.Paragraph code>{step.asset_id}</Typography.Paragraph>
      <ScenarioConfiguration step={step} />
      <Typography.Text>输入绑定</Typography.Text>
      <JsonBlock value={step.params} />
      {step.output ? <Typography.Paragraph>输出引用名：{step.output}</Typography.Paragraph> : null}
      {step.definition ? <>
        <Typography.Text>流程输入契约</Typography.Text><JsonBlock value={step.definition.inputs} />
        <Typography.Text>流程输出</Typography.Text><JsonBlock value={step.definition.outputs} />
        <ScenarioBindings definition={step.definition} />
      </> : null}
    </>,
  }))} />
}

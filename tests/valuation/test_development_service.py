import json,subprocess,sys,unittest,base64
from dataclasses import asdict
from io import BytesIO
from openpyxl import load_workbook
from balto_development.example import example_deal,example_inputs,downside_inputs
class DevelopmentServiceTest(unittest.TestCase):
    def invoke(self,operation,inputs):
        d=asdict(example_deal());d['closing']=d['closing'].isoformat()
        p=subprocess.run([sys.executable,'-m','balto_valuation.service'],input=json.dumps({'contractVersion':'1','operation':operation,'snapshot':{'deal':d,'inputs':inputs},'context':{'note':'Synthetic development only','basis':{'land_cost':{'kind':'assumption','reason':'=synthetic source'}}}}),text=True,capture_output=True,check=True)
        return json.loads(p.stdout)
    def test_saved_workflow_contract_returns_pinned_development_results_and_workbook(self):
        response=self.invoke('run',example_inputs());self.assertEqual(response['status'],'succeeded',response)
        result=response['result'];self.assertEqual(result['run']['modelId'],'multifamily-development')
        book=load_workbook(BytesIO(base64.b64decode(result['workbookBase64'])))
        self.assertEqual(book['Input Basis']['A2'].value,'Synthetic development only')
        self.assertEqual(book['Input Basis']['C4'].data_type,'s')
        self.assertEqual(book['Input Basis']['C4'].value,'=synthetic source')
        self.assertIn('Construction Loan',book.sheetnames)
        self.assertIn('Investor Waterfall',book.sheetnames)
        self.assertEqual(result['run']['metrics']['lp_irr']['status'],'ok')
        self.assertIn('gp_promote',result['run']['values'])
        down=self.invoke('validate',downside_inputs());self.assertEqual(down['status'],'succeeded',down)
        self.assertFalse(down['result']['run']['tests']['funded']['passed'])

    def test_investor_terms_are_explicit_and_unavailable_returns_remain_statuses(self):
        inputs=example_inputs();del inputs['lp_share']
        missing=self.invoke('validate',inputs)
        self.assertEqual(missing['status'],'invalid')
        inputs=example_inputs();inputs['market_rent']={'one':0}
        result=self.invoke('validate',inputs)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(result['result']['run']['metrics']['lp_irr']['status'],'no_sign_change')
        self.assertNotIn('rate',result['result']['run']['metrics']['lp_irr'])

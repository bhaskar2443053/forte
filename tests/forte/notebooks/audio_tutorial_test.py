from testbook import testbook
import os

@testbook(
    "docs/notebook_tutorial/Automatic_Speech_Recognition.ipynb", execute=False
)
def test_Automatic_Speech_Recognition(tb):
    # input file
    tb.execute_cell("input_file")
    # imports_1
    tb.execute_cell("imports_1")
    #processor 1
    tb.execute_cell("SpeakerSegmentation")
    
    tb.execute_cell("pipeline1")
    tb.execute_cell("import_2")
    # test Article ontology
    tb.execute_cell("AudioUtterance")
    tb.execute_cell("pipeline2")
    tb.execute_cell("inference")
"""
Created on July 10, 2013

@author: alfoa
"""
from __future__ import division, print_function , unicode_literals, absolute_import
import warnings
warnings.simplefilter('default', DeprecationWarning)

#External Modules------------------------------------------------------------------------------------
import numpy as np
from scipy import spatial, interpolate
import os
from glob import glob
import copy
import math
from collections import OrderedDict
import importlib
#External Modules End--------------------------------------------------------------------------------

#Internal Modules------------------------------------------------------------------------------------
import utils
import mathUtils
import DataObjects
from Assembler import Assembler
import SupervisedLearning
import MessageHandler
import GridEntities
import Files
from RAVENiterators import ravenArrayIterator
import unSupervisedLearning
from PostProcessorInterfaceBaseClass import PostProcessorInterfaceBase
#Internal Modules End--------------------------------------------------------------------------------

"""
  ***************************************
  *  SPECIALIZED PostProcessor CLASSES  *
  ***************************************
"""

class BasePostProcessor(Assembler, MessageHandler.MessageUser):
  """"This is the base class for postprocessors"""
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    self.type = self.__class__.__name__  # pp type
    self.name = self.__class__.__name__  # pp name
    self.assemblerObjects = {}  # {MainClassName(e.g.Distributions):[class(e.g.Models),type(e.g.ROM),objectName]}
    self.requiredAssObject = (False, ([], []))  # tuple. self.first entry boolean flag. True if the XML parser must look for assembler objects;
                                                      # second entry tuple.self.first entry list of object can be retrieved, second entry multiplicity (-1,-2,-n means optional (max 1 object,2 object, no number limit))
    self.assemblerDict = {}  # {'class':[['subtype','name',instance]]}
    self.messageHandler = messageHandler

  def initialize(self, runInfo, inputs, initDict) :
    """
     Method to initialize the pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    # if 'externalFunction' in initDict.keys(): self.externalFunction = initDict['externalFunction']
    self.inputs = inputs

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, list, list of current inputs
    """
    return [(copy.deepcopy(currentInput))]

  def run(self, Input):
    """
     This method executes the postprocessor action.
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, dictionary, Dictionary containing the evaluated data
    """
    pass

class LimitSurfaceIntegral(BasePostProcessor):
  """
  This post-processor is aimed to compute the n-dimensional integral of an inputted Limit Surface
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.variableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each variable.
    self.target = None  # target that defines the f(x1,x2,...,xn)
    self.tolerance = 0.0001  # integration tolerance
    self.integralType = 'montecarlo'  # integral type (which alg needs to be used). Either montecarlo or quadrature(quadrature not yet)
    self.seed = 20021986  # seed for montecarlo
    self.matrixDict = {}  # dictionary of arrays and target
    self.lowerUpperDict = {}
    self.functionS = None
    self.stat = returnInstance('BasicStatistics', self)  # instantiation of the 'BasicStatistics' processor, which is used to compute the pb given montecarlo evaluations
    self.stat.what = ['expectedValue']
    self.requiredAssObject = (False, (['Distribution'], ['n']))
    self.printTag = 'POSTPROCESSOR INTEGRAL'

  def _localWhatDoINeed(self):
    """
    This method is a local mirror of the general whatDoINeed method.
    It is implemented by this postprocessor that need to request special objects
    @ In , None, None
    @ Out, needDict, list of objects needed
    """
    needDict = {'Distributions':[]}
    for distName in self.variableDist.values():
      if distName != None: needDict['Distributions'].append((None, distName))
    return needDict

  def _localGenerateAssembler(self, initDict):
    """ see generateAssembler method in Assembler.py """
    for varName, distName in self.variableDist.items():
      if distName != None:
        if distName not in initDict['Distributions'].keys(): self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
        self.variableDist[varName] = initDict['Distributions'][distName]
        self.lowerUpperDict[varName]['lowerBound'] = self.variableDist[varName].lowerBound
        self.lowerUpperDict[varName]['upperBound'] = self.variableDist[varName].upperBound

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      varName = None
      if child.tag == 'variable':
        varName = child.attrib['name']
        self.lowerUpperDict[varName] = {}
        self.variableDist[varName] = None
        for childChild in child:
          if childChild.tag == 'distribution': self.variableDist[varName] = childChild.text
          elif childChild.tag == 'lowerBound':
            if self.variableDist[varName] != None: self.raiseAnError(NameError, 'you can not specify both distribution and lower/upper bounds nodes for variable ' + varName + ' !')
            self.lowerUpperDict[varName]['lowerBound'] = float(childChild.text)
          elif childChild.tag == 'upperBound':
            if self.variableDist[varName] != None: self.raiseAnError(NameError, 'you can not specify both distribution and lower/upper bounds nodes for variable ' + varName + ' !')
            self.lowerUpperDict[varName]['upperBound'] = float(childChild.text)
          else:
            self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution", "lowerBound" abd "upperBound" is accepted. tag: ' + child.tag)
      elif child.tag == 'tolerance':
        try              : self.tolerance = float(child.text)
        except ValueError: self.raiseAnError(ValueError, "tolerance can not be converted into a float value!")
      elif child.tag == 'integralType':
        self.integralType = child.text.strip().lower()
        if self.integralType not in ['montecarlo']: self.raiseAnError(IOError, 'only one integral types are available: MonteCarlo!')
      elif child.tag == 'seed':
        try              : self.seed = int(child.text)
        except ValueError: self.raiseAnError(ValueError, 'seed can not be converted into a int value!')
        if self.integralType != 'montecarlo': self.raiseAWarning('integral type is ' + self.integralType + ' but a seed has been inputted!!!')
        else: np.random.seed(self.seed)
      elif child.tag == 'target':
        self.target = child.text
      else: self.raiseAnError(NameError, 'invalid or missing labels after the variables call. Only "variable" is accepted.tag: ' + child.tag)
      # if no distribution, we look for the integration domain in the input
      if varName != None:
        if self.variableDist[varName] == None:
          if 'lowerBound' not in self.lowerUpperDict[varName].keys() or 'upperBound' not in self.lowerUpperDict[varName].keys():
            self.raiseAnError(NameError, 'either a distribution name or lowerBound and upperBound need to be specified for variable ' + varName)
    if self.target == None: self.raiseAWarning('integral target has not been provided. The postprocessor is going to take the last output it finds in the provided limitsurface!!!')

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the Limit Surface Integral post-processor. This method here
     is in charge of 'training' the nearest Neighbors ROM.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self.inputToInternal(inputs)
    if self.integralType in ['montecarlo']:
      self.stat.parameters['targets'] = [self.target]
      self.stat.initialize(runInfo, inputs, initDict)
    self.functionS = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'neighbors|KNeighborsClassifier', 'Features':','.join(list(self.variableDist.keys())), 'Target':self.target})
    self.functionS.train(self.matrixDict)
    self.raiseADebug('DATA SET MATRIX:')
    self.raiseADebug(self.matrixDict)

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    for item in currentInput:
      if item.type == 'PointSet':
        self.matrixDict = {}
        if not set(item.getParaKeys('inputs')) == set(self.variableDist.keys()): self.raiseAnError(IOError, 'The variables inputted and the features in the input PointSet ' + item.name + 'do not match!!!')
        if self.target == None: self.target = item.getParaKeys('outputs')[-1]
        if self.target not in item.getParaKeys('outputs'): self.raiseAnError(IOError, 'The target ' + self.target + 'is not present among the outputs of the PointSet ' + item.name)
        # construct matrix
        for  varName in self.variableDist.keys(): self.matrixDict[varName] = item.getParam('input', varName)
        outputarr = item.getParam('output', self.target)
        if len(set(outputarr)) != 2: self.raiseAnError(IOError, 'The target ' + self.target + ' needs to be a classifier output (-1 +1 or 0 +1)!')
        outputarr[outputarr == -1] = 0.0
        self.matrixDict[self.target] = outputarr
      else: self.raiseAnError(IOError, 'Only PointSet is accepted as input!!!!')

  def run(self, Input):
    """
     This method executes the postprocessor action. In this case, it performs the computation of the LS integral
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, float, integral outcome (probability of the event)
    """
    pb = None
    if self.integralType == 'montecarlo':
      tempDict = {}
      randomMatrix = np.random.rand(int(math.ceil(1.0 / self.tolerance**2)), len(self.variableDist.keys()))
      for index, varName in enumerate(self.variableDist.keys()):
        if self.variableDist[varName] == None: randomMatrix[:, index] = randomMatrix[:, index] * (self.lowerUpperDict[varName]['upperBound'] - self.lowerUpperDict[varName]['lowerBound']) + self.lowerUpperDict[varName]['lowerBound']
        else:
          for samples in range(randomMatrix.shape[0]): randomMatrix[samples, index] = self.variableDist[varName].ppf(randomMatrix[samples, index])
        tempDict[varName] = randomMatrix[:, index]
      pb = self.stat.run({'targets':{self.target:self.functionS.evaluate(tempDict)}})
    else: self.raiseAnError(NotImplemented, "quadrature not yet implemented")
    return pb['expectedValue'][self.target]

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'no available output to collect.')
    else:
      pb = finishedjob.returnEvaluation()[1]
      lms = finishedjob.returnEvaluation()[0][0]
      if output.type == 'PointSet':
        # we store back the limitsurface
        for key, value in lms.getParametersValues('input').items():
          for val in value: output.updateInputValue(key, val)
        for key, value in lms.getParametersValues('output').items():
          for val in value: output.updateOutputValue(key, val)
        for _ in range(len(lms)): output.updateOutputValue('EventProbability', pb)
      elif isinstance(output,Files.File):
        headers = lms.getParaKeys('inputs') + lms.getParaKeys('outputs')
        if 'EventProbability' not in headers: headers += ['EventProbability']
        stack = [None] * len(headers)
        output.close()
        outIndex = 0
        for key, value in lms.getParametersValues('input').items() : stack[headers.index(key)] = np.asarray(value).flatten()
        for key, value in lms.getParametersValues('output').items():
          stack[headers.index(key)] = np.asarray(value).flatten()
          outIndex = headers.index(key)
        stack[headers.index('EventProbability')] = np.array([pb] * len(stack[outIndex])).flatten()
        stacked = np.column_stack(stack)
        np.savetxt(output, stacked, delimiter = ',', header = ','.join(headers),comments='')
        #N.B. without comments='' you get a "# " at the top of the header row
      else: self.raiseAnError(Exception, self.type + ' accepts PointSet or File type only')
#
#
#
class SafestPoint(BasePostProcessor):
  """
  It searches for the probability-weighted safest point inside the space of the system controllable variables
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.controllableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each controllale variable.
    self.nonControllableDist = {}  # dictionary created upon the .xml input file reading. It stores the distributions for each non-controllale variable.
    self.controllableGrid = {}  # dictionary created upon the .xml input file reading. It stores the grid type ('value' or 'CDF'), the number of steps and the step length for each controllale variable.
    self.nonControllableGrid = {}  # dictionary created upon the .xml input file reading. It stores the grid type ('value' or 'CDF'), the number of steps and the step length for each non-controllale variable.
    self.gridInfo = {}  # dictionary contaning the grid type ('value' or 'CDF'), the grid construction type ('equal', set by default) and the list of sampled points for each variable.
    self.controllableOrd = []  # list contaning the controllable variables' names in the same order as they appear inside the controllable space (self.controllableSpace)
    self.nonControllableOrd = []  # list contaning the controllable variables' names in the same order as they appear inside the non-controllable space (self.nonControllableSpace)
    self.surfPointsMatrix = None  # 2D-matrix containing the coordinates of the points belonging to the failure boundary (coordinates are derived from both the controllable and non-controllable space)
    self.stat = returnInstance('BasicStatistics', self)  # instantiation of the 'BasicStatistics' processor, which is used to compute the expected value of the safest point through the coordinates and probability values collected in the 'run' function
    self.stat.what = ['expectedValue']
    self.requiredAssObject = (True, (['Distribution'], ['n']))
    self.printTag = 'POSTPROCESSOR SAFESTPOINT'

  def _localGenerateAssembler(self, initDict):
    """ see generateAssembler method in Assembler """
    for varName, distName in self.controllableDist.items():
      if distName not in initDict['Distributions'].keys():
        self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
      self.controllableDist[varName] = initDict['Distributions'][distName]
    for varName, distName in self.nonControllableDist.items():
      if distName not in initDict['Distributions'].keys():
        self.raiseAnError(IOError, 'distribution ' + distName + ' not found.')
      self.nonControllableDist[varName] = initDict['Distributions'][distName]

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'controllable':
        for childChild in child:
          if childChild.tag == 'variable':
            varName = childChild.attrib['name']
            for childChildChild in childChild:
              if childChildChild.tag == 'distribution':
                self.controllableDist[varName] = childChildChild.text
              elif childChildChild.tag == 'grid':
                if 'type' in childChildChild.attrib.keys():
                  if 'steps' in childChildChild.attrib.keys():
                    self.controllableGrid[varName] = (childChildChild.attrib['type'], int(childChildChild.attrib['steps']), float(childChildChild.text))
                  else:
                    self.raiseAnError(NameError, 'number of steps missing after the grid call.')
                else:
                  self.raiseAnError(NameError, 'grid type missing after the grid call.')
              else:
                self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution" and "grid" are accepted.')
          else:
            self.raiseAnError(NameError, 'invalid or missing labels after the controllable variables call. Only "variable" is accepted.')
      elif child.tag == 'non-controllable':
        for childChild in child:
          if childChild.tag == 'variable':
            varName = childChild.attrib['name']
            for childChildChild in childChild:
              if childChildChild.tag == 'distribution':
                self.nonControllableDist[varName] = childChildChild.text
              elif childChildChild.tag == 'grid':
                if 'type' in childChildChild.attrib.keys():
                  if 'steps' in childChildChild.attrib.keys():
                    self.nonControllableGrid[varName] = (childChildChild.attrib['type'], int(childChildChild.attrib['steps']), float(childChildChild.text))
                  else:
                    self.raiseAnError(NameError, 'number of steps missing after the grid call.')
                else:
                  self.raiseAnError(NameError, 'grid type missing after the grid call.')
              else:
                self.raiseAnError(NameError, 'invalid labels after the variable call. Only "distribution" and "grid" are accepted.')
          else:
            self.raiseAnError(NameError, 'invalid or missing labels after the controllable variables call. Only "variable" is accepted.')
    self.raiseADebug('CONTROLLABLE DISTRIBUTIONS:')
    self.raiseADebug(self.controllableDist)
    self.raiseADebug('CONTROLLABLE GRID:')
    self.raiseADebug(self.controllableGrid)
    self.raiseADebug('NON-CONTROLLABLE DISTRIBUTIONS:')
    self.raiseADebug(self.nonControllableDist)
    self.raiseADebug('NON-CONTROLLABLE GRID:')
    self.raiseADebug(self.nonControllableGrid)

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the Safest Point pp. This method is in charge
     of creating the Controllable and no-controllable grid.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self.__gridSetting__()
    self.__gridGeneration__()
    self.inputToInternal(inputs)
    self.stat.parameters['targets'] = self.controllableOrd
    self.stat.initialize(runInfo, inputs, initDict)
    self.raiseADebug('GRID INFO:')
    self.raiseADebug(self.gridInfo)
    self.raiseADebug('N-DIMENSIONAL CONTROLLABLE SPACE:')
    self.raiseADebug(self.controllableSpace)
    self.raiseADebug('N-DIMENSIONAL NON-CONTROLLABLE SPACE:')
    self.raiseADebug(self.nonControllableSpace)
    self.raiseADebug('CONTROLLABLE VARIABLES ORDER:')
    self.raiseADebug(self.controllableOrd)
    self.raiseADebug('NON-CONTROLLABLE VARIABLES ORDER:')
    self.raiseADebug(self.nonControllableOrd)
    self.raiseADebug('SURFACE POINTS MATRIX:')
    self.raiseADebug(self.surfPointsMatrix)

  def __gridSetting__(self, constrType = 'equal'):
    for varName in self.controllableGrid.keys():
      if self.controllableGrid[varName][0] == 'value':
        self.__stepError__(float(self.controllableDist[varName].lowerBound), float(self.controllableDist[varName].upperBound), self.controllableGrid[varName][1], self.controllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.controllableGrid[varName][0], constrType, [float(self.controllableDist[varName].lowerBound) + self.controllableGrid[varName][2] * i for i in range(self.controllableGrid[varName][1] + 1)])
      elif self.controllableGrid[varName][0] == 'CDF':
        self.__stepError__(0, 1, self.controllableGrid[varName][1], self.controllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.controllableGrid[varName][0], constrType, [self.controllableGrid[varName][2] * i for i in range(self.controllableGrid[varName][1] + 1)])
      else:
        self.raiseAnError(NameError, 'inserted invalid grid type. Only "value" and "CDF" are accepted.')
    for varName in self.nonControllableGrid.keys():
      if self.nonControllableGrid[varName][0] == 'value':
        self.__stepError__(float(self.nonControllableDist[varName].lowerBound), float(self.nonControllableDist[varName].upperBound), self.nonControllableGrid[varName][1], self.nonControllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.nonControllableGrid[varName][0], constrType, [float(self.nonControllableDist[varName].lowerBound) + self.nonControllableGrid[varName][2] * i for i in range(self.nonControllableGrid[varName][1] + 1)])
      elif self.nonControllableGrid[varName][0] == 'CDF':
        self.__stepError__(0, 1, self.nonControllableGrid[varName][1], self.nonControllableGrid[varName][2], varName)
        self.gridInfo[varName] = (self.nonControllableGrid[varName][0], constrType, [self.nonControllableGrid[varName][2] * i for i in range(self.nonControllableGrid[varName][1] + 1)])
      else:
        self.raiseAnError(NameError, 'inserted invalid grid type. Only "value" and "CDF" are accepted.')

  def __stepError__(self, lowerBound, upperBound, steps, tol, varName):
    if upperBound - lowerBound < steps * tol:
      self.raiseAnError(IOError, 'requested number of steps or tolerance for variable ' + varName + ' exceeds its limit.')

  def __gridGeneration__(self):
    NotchesByVar = [None] * len(self.controllableGrid.keys())
    controllableSpaceSize = None
    for varId, varName in enumerate(self.controllableGrid.keys()):
      NotchesByVar[varId] = self.controllableGrid[varName][1] + 1
      self.controllableOrd.append(varName)
    controllableSpaceSize = tuple(NotchesByVar + [len(self.controllableGrid.keys())])
    self.controllableSpace = np.zeros(controllableSpaceSize)
    iterIndex = ravenArrayIterator(arrayIn=self.controllableSpace)
    while not iterIndex.finished:
      coordIndex = iterIndex.multiIndex[-1]
      varName = list(self.controllableGrid.keys())[coordIndex]
      notchPos = iterIndex.multiIndex[coordIndex]
      if self.gridInfo[varName][0] == 'CDF':
        valList = []
        for probVal in self.gridInfo[varName][2]:
          valList.append(self.controllableDist[varName].cdf(probVal))
        self.controllableSpace[iterIndex.multiIndex] = valList[notchPos]
      else:
        self.controllableSpace[iterIndex.multiIndex] = self.gridInfo[varName][2][notchPos]
      iterIndex.iternext()
    NotchesByVar = [None] * len(self.nonControllableGrid.keys())
    nonControllableSpaceSize = None
    for varId, varName in enumerate(self.nonControllableGrid.keys()):
      NotchesByVar[varId] = self.nonControllableGrid[varName][1] + 1
      self.nonControllableOrd.append(varName)
    nonControllableSpaceSize = tuple(NotchesByVar + [len(self.nonControllableGrid.keys())])
    self.nonControllableSpace = np.zeros(nonControllableSpaceSize)
    iterIndex = ravenArrayIterator(arrayIn=self.nonControllableSpace)
    while not iterIndex.finished:
      coordIndex = iterIndex.multiIndex[-1]
      varName = list(self.nonControllableGrid.keys())[coordIndex]
      notchPos = iterIndex.multiIndex[coordIndex]
      if self.gridInfo[varName][0] == 'CDF':
        valList = []
        for probVal in self.gridInfo[varName][2]:
          valList.append(self.nonControllableDist[varName].cdf(probVal))
        self.nonControllableSpace[iterIndex.multiIndex] = valList[notchPos]
      else:
        self.nonControllableSpace[iterIndex.multiIndex] = self.gridInfo[varName][2][notchPos]
      iterIndex.iternext()

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    for item in currentInput:
      if item.type == 'PointSet':
        self.surfPointsMatrix = np.zeros((len(item.getParam('output', item.getParaKeys('outputs')[-1])), len(self.gridInfo.keys()) + 1))
        k = 0
        for varName in self.controllableOrd:
          self.surfPointsMatrix[:, k] = item.getParam('input', varName)
          k += 1
        for varName in self.nonControllableOrd:
          self.surfPointsMatrix[:, k] = item.getParam('input', varName)
          k += 1
        self.surfPointsMatrix[:, k] = item.getParam('output', item.getParaKeys('outputs')[-1])

  def run(self, Input):
    """
     This method executes the postprocessor action. In this case, it computes the safest point
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, PointSet, PointSet containing the elaborated data
    """
    nearestPointsInd = []
    dataCollector = DataObjects.returnInstance('PointSet', self)
    dataCollector.type = 'PointSet'
    surfTree = spatial.KDTree(copy.copy(self.surfPointsMatrix[:, 0:self.surfPointsMatrix.shape[-1] - 1]))
    self.controllableSpace.shape = (np.prod(self.controllableSpace.shape[0:len(self.controllableSpace.shape) - 1]), self.controllableSpace.shape[-1])
    self.nonControllableSpace.shape = (np.prod(self.nonControllableSpace.shape[0:len(self.nonControllableSpace.shape) - 1]), self.nonControllableSpace.shape[-1])
    self.raiseADebug('RESHAPED CONTROLLABLE SPACE:')
    self.raiseADebug(self.controllableSpace)
    self.raiseADebug('RESHAPED NON-CONTROLLABLE SPACE:')
    self.raiseADebug(self.nonControllableSpace)
    for ncLine in range(self.nonControllableSpace.shape[0]):
      queryPointsMatrix = np.append(self.controllableSpace, np.tile(self.nonControllableSpace[ncLine, :], (self.controllableSpace.shape[0], 1)), axis = 1)
      self.raiseADebug('QUERIED POINTS MATRIX:')
      self.raiseADebug(queryPointsMatrix)
      nearestPointsInd = surfTree.query(queryPointsMatrix)[-1]
      distList = []
      indexList = []
      probList = []
      for index in range(len(nearestPointsInd)):
        if self.surfPointsMatrix[np.where(np.prod(surfTree.data[nearestPointsInd[index], 0:self.surfPointsMatrix.shape[-1] - 1] == self.surfPointsMatrix[:, 0:self.surfPointsMatrix.shape[-1] - 1], axis = 1))[0][0], -1] == 1:
          distList.append(np.sqrt(np.sum(np.power(queryPointsMatrix[index, 0:self.controllableSpace.shape[-1]] - surfTree.data[nearestPointsInd[index], 0:self.controllableSpace.shape[-1]], 2))))
          indexList.append(index)
      if distList == []:
        self.raiseAnError(ValueError, 'no safest point found for the current set of non-controllable variables: ' + str(self.nonControllableSpace[ncLine, :]) + '.')
      else:
        for cVarIndex in range(len(self.controllableOrd)):
          dataCollector.updateInputValue(self.controllableOrd[cVarIndex], copy.copy(queryPointsMatrix[indexList[distList.index(max(distList))], cVarIndex]))
        for ncVarIndex in range(len(self.nonControllableOrd)):
          dataCollector.updateInputValue(self.nonControllableOrd[ncVarIndex], copy.copy(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex]))
          if queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] == self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].lowerBound:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)
            else:
              prob = self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].lowerBound + self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          elif queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] == self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].upperBound:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)
            else:
              prob = 1 - self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].upperBound - self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          else:
            if self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][0] == 'CDF':
              prob = self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2]
            else:
              prob = self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] + self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2)) - self.nonControllableDist[self.nonControllableOrd[ncVarIndex]].cdf(queryPointsMatrix[indexList[distList.index(max(distList))], len(self.controllableOrd) + ncVarIndex] - self.nonControllableGrid[self.nonControllableOrd[ncVarIndex]][2] / float(2))
          probList.append(prob)
      dataCollector.updateOutputValue('Probability', np.prod(probList))
      dataCollector.updateMetadata('ProbabilityWeight', np.prod(probList))
    dataCollector.updateMetadata('ExpectedSafestPointCoordinates', self.stat.run(dataCollector)['expectedValue'])
    self.raiseADebug(dataCollector.getParametersValues('input'))
    self.raiseADebug(dataCollector.getParametersValues('output'))
    self.raiseADebug(dataCollector.getMetadata('ExpectedSafestPointCoordinates'))
    return dataCollector

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1:
      self.raiseAnError(RuntimeError, 'no available output to collect (the run is likely not over yet).')
    else:
      dataCollector = finishedjob.returnEvaluation()[1]
      if output.type != 'PointSet':
        self.raiseAnError(TypeError, 'output item type must be "PointSet".')
      else:
        if not output.isItEmpty():
          self.raiseAnError(ValueError, 'output item must be empty.')
        else:
          for key, value in dataCollector.getParametersValues('input').items():
            for val in value: output.updateInputValue(key, val)
          for key, value in dataCollector.getParametersValues('output').items():
            for val in value: output.updateOutputValue(key, val)
          for key, value in dataCollector.getAllMetadata().items(): output.updateMetadata(key, value)
#
#
#
class ComparisonStatistics(BasePostProcessor):
  """
  ComparisonStatistics is to calculate statistics that compare
  two different codes or code to experimental data.
  """

  class CompareGroup:
    def __init__(self):
      """
       Constructor
      """
      self.dataPulls = []
      self.referenceData = {}

  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.dataDict = {}  # Dictionary of all the input data, keyed by the name
    self.compareGroups = []  # List of each of the groups that will be compared
    # self.dataPulls = [] #List of data references that will be used
    # self.referenceData = [] #List of reference (experimental) data
    self.methodInfo = {}  # Information on what stuff to do.
    self.fZStats = False
    self.interpolation = "quadratic"
    self.requiredAssObject = (True, (['Distribution'], ['-n']))
    self.distributions = {}

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, object, the resulting converted object
    """
    return [(currentInput)]

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the ComparisonStatistics pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for outer in xmlNode:
      if outer.tag == 'compare':
        compareGroup = ComparisonStatistics.CompareGroup()
        for child in outer:
          if child.tag == 'data':
            dataName = child.text
            splitName = dataName.split("|")
            name, kind = splitName[:2]
            rest = splitName[2:]
            compareGroup.dataPulls.append([name, kind, rest])
          elif child.tag == 'reference':
            # This has name=distribution
            compareGroup.referenceData = dict(child.attrib)
            if "name" not in compareGroup.referenceData:
              self.raiseAnError(IOError, 'Did not find name in reference block')

        self.compareGroups.append(compareGroup)
      if outer.tag == 'kind':
        self.methodInfo['kind'] = outer.text
        if 'numBins' in outer.attrib:
          self.methodInfo['numBins'] = int(outer.attrib['numBins'])
        if 'binMethod' in outer.attrib:
          self.methodInfo['binMethod'] = outer.attrib['binMethod'].lower()
      if outer.tag == 'fz':
        self.fZStats = (outer.text.lower() in utils.stringsThatMeanTrue())
      if outer.tag == 'interpolation':
        interpolation = outer.text.lower()
        if interpolation == 'linear':
          self.interpolation = 'linear'
        elif interpolation == 'quadratic':
          self.interpolation = 'quadratic'
        else:
          self.raiseADebug('unexpected interpolation method ' + interpolation)
          self.interpolation = interpolation


  def _localGenerateAssembler(self, initDict):
    self.distributions = initDict.get('Distributions', {})
    # print("initDict", initDict)

  def run(self, Input):  # inObj,workingDir=None):
    """
     This method executes the postprocessor action. In this case, it just returns the inputs
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, dictionary, Dictionary containing the inputs
    """
    dataDict = {}
    for aInput in Input: dataDict[aInput.name] = aInput
    return dataDict

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    self.raiseADebug("finishedjob: " + str(finishedjob) + ", output " + str(output))
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'no available output to collect.')
    else: self.dataDict.update(finishedjob.returnEvaluation()[1])

    dataToProcess = []
    for compareGroup in self.compareGroups:
      dataPulls = compareGroup.dataPulls
      reference = compareGroup.referenceData
      foundDataObjects = []
      for name, kind, rest in dataPulls:
        data = self.dataDict[name].getParametersValues(kind)
        if len(rest) == 1:
          foundDataObjects.append(data[rest[0]])
      dataToProcess.append((dataPulls, foundDataObjects, reference))
    generateCSV = False
    generatePointSet = False
    if isinstance(output,Files.File):
      generateCSV = True
    elif output.type == 'PointSet':
      generatePointSet = True
    else:
      self.raiseAnError(IOError, 'unsupported type ' + str(type(output)))
    if generateCSV:
      csv = output
    for dataPulls, datas, reference in dataToProcess:
      graphData = []
      if "name" in reference:
        distributionName = reference["name"]
        if not distributionName in self.distributions:
          self.raiseAnError(IOError, 'Did not find ' + distributionName +
                             ' in ' + str(self.distributions.keys()))
        else:
          distribution = self.distributions[distributionName]
        refDataStats = {"mean":distribution.untruncatedMean(),
                        "stdev":distribution.untruncatedStdDev()}
        refDataStats["minBinSize"] = refDataStats["stdev"] / 2.0
        refPdf = lambda x:distribution.pdf(x)
        refCdf = lambda x:distribution.cdf(x)
        graphData.append((refDataStats, refCdf, refPdf, "ref_" + distributionName))
      for dataPull, data in zip(dataPulls, datas):
        dataStats = self.processData(dataPull, data, self.methodInfo)
        dataKeys = set(dataStats.keys())
        counts = dataStats['counts']
        bins = dataStats['bins']
        countSum = sum(counts)
        binBoundaries = [dataStats['low']] + bins + [dataStats['high']]
        if generateCSV:
          utils.printCsv(csv, '"' + str(dataPull) + '"')
          utils.printCsv(csv, '"numBins"', dataStats['numBins'])
          utils.printCsv(csv, '"binBoundary"', '"binMidpoint"', '"binCount"', '"normalizedBinCount"', '"f_prime"', '"cdf"')
        cdf = [0.0] * len(counts)
        midpoints = [0.0] * len(counts)
        cdfSum = 0.0
        for i in range(len(counts)):
          f0 = counts[i] / countSum
          cdfSum += f0
          cdf[i] = cdfSum
          midpoints[i] = (binBoundaries[i] + binBoundaries[i + 1]) / 2.0
        cdfFunc = mathUtils.createInterp(midpoints, cdf, 0.0, 1.0, self.interpolation)
        fPrimeData = [0.0] * len(counts)
        for i in range(len(counts)):
          h = binBoundaries[i + 1] - binBoundaries[i]
          nCount = counts[i] / countSum  # normalized count
          f0 = cdf[i]
          if i + 1 < len(counts):
            f1 = cdf[i + 1]
          else:
            f1 = 1.0
          if i + 2 < len(counts):
            f2 = cdf[i + 2]
          else:
            f2 = 1.0
          if self.interpolation == 'linear':
            fPrime = (f1 - f0) / h
          else:
            fPrime = (-1.5 * f0 + 2.0 * f1 + -0.5 * f2) / h
          fPrimeData[i] = fPrime
          if generateCSV:
            utils.printCsv(csv, binBoundaries[i + 1], midpoints[i], counts[i], nCount, fPrime, cdf[i])
        pdfFunc = mathUtils.createInterp(midpoints, fPrimeData, 0.0, 0.0, self.interpolation)
        dataKeys -= set({'numBins', 'counts', 'bins'})
        if generateCSV:
          for key in dataKeys:
            utils.printCsv(csv, '"' + key + '"', dataStats[key])
        self.raiseADebug("dataStats: " + str(dataStats))
        graphData.append((dataStats, cdfFunc, pdfFunc, str(dataPull)))
      graphDataDict = mathUtils.getGraphs(graphData, self.fZStats)
      if generateCSV:
        for key in graphDataDict:
          value = graphDataDict[key]
          if type(value).__name__ == 'list':
            utils.printCsv(csv, *(['"' + l[0] + '"' for l in value]))
            for i in range(1, len(value[0])):
              utils.printCsv(csv, *([l[i] for l in value]))
          else:
            utils.printCsv(csv, '"' + key + '"', value)
      if generatePointSet:
        for key in graphDataDict:
          value = graphDataDict[key]
          if type(value).__name__ == 'list':
            for i in range(len(value)):
              subvalue = value[i]
              name = subvalue[0]
              subdata = subvalue[1:]
              if i == 0:
                output.updateInputValue(name, subdata)
              else:
                output.updateOutputValue(name, subdata)
            break  # XXX Need to figure out way to specify which data to return
      if generateCSV:
        for i in range(len(graphData)):
          dataStat = graphData[i][0]
          def delist(l):
            if type(l).__name__ == 'list':
              return '_'.join([delist(x) for x in l])
            else:
              return str(l)
          newFileName = output.getBase() + "_" + delist(dataPulls) + "_" + str(i) + ".csv"
          if type(dataStat).__name__ != 'dict':
            assert(False)
            continue
          dataPairs = []
          for key in sorted(dataStat.keys()):
            value = dataStat[key]
            if np.isscalar(value):
              dataPairs.append((key, value))
          extraCsv = Files.returnInstance('CSV',self)
          extraCsv.initialize(newFileName,self.messageHandler)
          extraCsv.open("w")
          extraCsv.write(",".join(['"' + str(x[0]) + '"' for x in dataPairs]))
          extraCsv.write("\n")
          extraCsv.write(",".join([str(x[1]) for x in dataPairs]))
          extraCsv.write("\n")
          extraCsv.close()
        utils.printCsv(csv)

  def processData(self, dataPull, data, methodInfo):
      ret = {}
      if hasattr(data,'tolist'):
        sortedData = data.tolist()
      else:
        sortedData = list(data)
      sortedData.sort()
      low = sortedData[0]
      high = sortedData[-1]
      dataRange = high - low
      ret['low'] = low
      ret['high'] = high
      if not 'binMethod' in methodInfo:
        numBins = methodInfo.get("numBins", 10)
      else:
        binMethod = methodInfo['binMethod']
        dataN = len(sortedData)
        if binMethod == 'square-root':
          numBins = int(math.ceil(math.sqrt(dataN)))
        elif binMethod == 'sturges':
          numBins = int(math.ceil(mathUtils.log2(dataN) + 1))
        else:
          self.raiseADebug("Unknown binMethod " + binMethod, 'ExceptedError')
          numBins = 5
      ret['numBins'] = numBins
      kind = methodInfo.get("kind", "uniformBins")
      if kind == "uniformBins":
        bins = [low + x * dataRange / numBins for x in range(1, numBins)]
        ret['minBinSize'] = dataRange / numBins
      elif kind == "equalProbability":
        stride = len(sortedData) // numBins
        bins = [sortedData[x] for x in range(stride - 1, len(sortedData) - stride + 1, stride)]
        if len(bins) > 1:
          ret['minBinSize'] = min(map(lambda x, y: x - y, bins[1:], bins[:-1]))
        else:
          ret['minBinSize'] = dataRange
      counts = mathUtils.countBins(sortedData, bins)
      ret['bins'] = bins
      ret['counts'] = counts
      ret.update(mathUtils.calculateStats(sortedData))
      skewness = ret["skewness"]
      delta = math.sqrt((math.pi / 2.0) * (abs(skewness) ** (2.0 / 3.0)) /
                        (abs(skewness) ** (2.0 / 3.0) + ((4.0 - math.pi) / 2.0) ** (2.0 / 3.0)))
      delta = math.copysign(delta, skewness)
      alpha = delta / math.sqrt(1.0 - delta ** 2)
      variance = ret["sampleVariance"]
      omega = variance / (1.0 - 2 * delta ** 2 / math.pi)
      mean = ret['mean']
      xi = mean - omega * delta * math.sqrt(2.0 / math.pi)
      ret['alpha'] = alpha
      ret['omega'] = omega
      ret['xi'] = xi
      return ret
#
#
#

class InterfacedPostProcessor(BasePostProcessor):
  """
  This class allows to interface a general-purpose post-processor created ad-hoc by the user.
  While the ExternalPostProcessor is designed for analysis-dependent cases, the InterfacedPostProcessor is designed more generic cases
  The InterfacedPostProcessor parses (see PostProcessorInterfaces.py) and uses only the functions contained in the raven/framework/PostProcessorFunctions folder
  The base class for the InterfacedPostProcessor that the user has to inherit to develop its own InterfacedPostProcessor is specified
  in PostProcessorInterfaceBase.py
  """

  PostProcessorInterfaces = importlib.import_module("PostProcessorInterfaces")

  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
     @ Out, None
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.methodToRun = None

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the Interfaced Post-processor
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
#     self.postProcessor.initialize()
#
#     if self.postProcessor.inputFormat not in set(['HistorySet','History','PointSet','Point']):
#       self.raiseAnError(IOError,'InterfacedPostProcessor Post-Processor '+ self.name +' : self.inputFormat not correctly initialized')
#     if self.postProcessor.outputFormat not in set(['HistorySet','History','PointSet','Point']):
#       self.raiseAnError(IOError,'InterfacedPostProcessor Post-Processor '+ self.name +' : self.outputFormat not correctly initialized')

  def _localReadMoreXML(self, xmlNode):
    """
      Function that reads elements this post-processor will use
      @ In, xmlNode, ElementTree, Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'method':
        self.methodToRun = child.text
    self.postProcessor = InterfacedPostProcessor.PostProcessorInterfaces.returnPostProcessorInterface(self.methodToRun,self)
    if not isinstance(self.postProcessor,PostProcessorInterfaceBase):
      self.raiseAnError(IOError,'InterfacedPostProcessor Post-Processor '+ self.name +' : not correctly coded; it must inherit the PostProcessorInterfaceBase class')

    self.postProcessor.initialize()
    if self.postProcessor.inputFormat not in set(['HistorySet','History','PointSet','Point']):
      self.raiseAnError(IOError,'InterfacedPostProcessor Post-Processor '+ self.name +' : self.inputFormat not correctly initialized')
    if self.postProcessor.outputFormat not in set(['HistorySet','History','PointSet','Point']):
      self.raiseAnError(IOError,'InterfacedPostProcessor Post-Processor '+ self.name +' : self.outputFormat not correctly initialized')
    self.postProcessor.readMoreXML(xmlNode)


  def run(self, InputIn):
    """
     This method executes the interfaced  post-processor action.
     @ In , InputIn, dict, dictionary of data to process
     @ Out, dictionary, dict containing the post-processed results
    """
    inputDic= self.inputToInternal(InputIn)
    outputDic = self.postProcessor.run(inputDic)
    if self.postProcessor.checkGeneratedDicts(outputDic):
      return outputDic
    else:
      self.raiseAnError(RuntimeError,'InterfacedPostProcessor Post-Processor: function has generated a not valid output dictionary')


  def collectOutput(self, finishedjob, output):
    """
      Function that fills the computed data into the output dataObject
      @ In, finishedJob, A JobHandler object that is in charge of running this post-processor
      @ In, jobHandler, jobHandler object, jobHandler instance
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1:
      self.raiseAnError(RuntimeError, ' No available Output to collect (Run probably is not finished yet)')
    evaluation = finishedjob.returnEvaluation()[1]
    exportDict = {'inputSpaceParams':evaluation['data']['input'],'outputSpaceParams':evaluation['data']['output'],'metadata':evaluation['metadata']}

    listInputParms   = output.getParaKeys('inputs')
    listOutputParams = output.getParaKeys('outputs')

    if output.type == 'HistorySet':
      for hist in exportDict['inputSpaceParams']:
        if type(exportDict['inputSpaceParams'].values()[0]).__name__ == "dict":
          for key in listInputParms:
            output.updateInputValue(key,exportDict['inputSpaceParams'][hist][key])
          for key in listOutputParams:
            output.updateOutputValue(key,exportDict['outputSpaceParams'][hist][key])
          for key in exportDict['metadata'][0]:
            output.updateMetadata(key,exportDict['metadata'][0][key])
        else:
          for key in exportDict['inputSpaceParams']:
            if key in output.getParaKeys('inputs'):
              output.updateInputValue(key,exportDict['inputSpaceParams'][key])
          for key in exportDict['outputSpaceParams']:
            if key in output.getParaKeys('outputs'):
              output.updateOutputValue(key,exportDict['outputSpaceParams'][key])
          for key in exportDict['metadata'][0]:
            output.updateMetadata(key,exportDict['metadata'][0][key])
    elif output.type == 'PointSet':
      for key in exportDict['inputSpaceParams']:
        if key in output.getParaKeys('inputs'):
          for value in exportDict['inputSpaceParams'][key]:
            output.updateInputValue(key,value)
      for key in exportDict['outputSpaceParams']:
        if key in output.getParaKeys('outputs'):
          for value in exportDict['outputSpaceParams'][key]:
            output.updateOutputValue(key,value)
      for key in exportDict['metadata'][0]:
        output.updateMetadata(key,exportDict['metadata'][0][key])

  def inputToInternal(self,input):
    """
      Function to convert the received input into a format this object can
      understand
      @ In, input, dataObject, data object handed to the post-processor
      @ Out, inputDict, dict, a dictionary this object can process
    """
    inputDict = {'data':{}, 'metadata':{}}
    metadata = []
    if type(input) == dict:
      return input
    else:
      inputDict['data']['input']  = copy.deepcopy(input[0].getInpParametersValues())
      inputDict['data']['output'] = copy.deepcopy(input[0].getOutParametersValues())
    for item in input:
      metadata.append(copy.deepcopy(item.getAllMetadata()))
    metadata.append(item.getAllMetadata())
    inputDict['metadata']=metadata
    return inputDict

#
#
#
class PrintCSV(BasePostProcessor):
  """
  PrintCSV PostProcessor class. It prints a CSV file loading data from a hdf5 database or other sources
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.paramters = ['all']
    self.inObj = None
    self.workingDir = None
    self.printTag = 'POSTPROCESSOR PRINTCSV'

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, None, the resulting converted object is stored as an attribute of this class
    """
    return [(currentInput)]

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the PrintCSV pp. In here, the workingdir is collected and eventually created
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.workingDir = os.path.join(runInfo['WorkingDir'], runInfo['stepName'])  # generate current working dir
    runInfo['TempWorkingDir'] = self.workingDir
    try:                            os.mkdir(self.workingDir)
    except:                         self.raiseAWarning('current working dir ' + self.workingDir + ' already exists, this might imply deletion of present files')
    # if type(inputs[-1]).__name__ == "HDF5" : self.inObj = inputs[-1]      # this should go in run return but if HDF5, it is not pickable

  def _localReadMoreXML(self, xmlNode):
    """
    Function to read the portion of the xml input that belongs to this specialized class
    and initialize some stuff based on the inputs got
    @ In, xmlNode    : Xml element node
    @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'parameters':
        param = child.text
        if(param.lower() != 'all'): self.paramters = param.strip().split(',')
        else: self.paramters[param]

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    # Check the input type
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'No available Output to collect (Run probabably is not finished yet)')
    self.inObj = finishedjob.returnEvaluation()[1]
    if(self.inObj.type == "HDF5"):
      #  Input source is a database (HDF5)
      #  Retrieve the ending groups' names
      endGroupNames = self.inObj.getEndingGroupNames()
      HistorySet = {}

      #  Construct a dictionary of all the HistorySet
      for index in range(len(endGroupNames)): HistorySet[endGroupNames[index]] = self.inObj.returnHistory({'history':endGroupNames[index], 'filter':'whole'})
      #  If file, split the strings and add the working directory if present
      for key in HistorySet:
        #  Loop over HistorySet
        #  Retrieve the metadata (posion 1 of the history tuple)
        attributes = HistorySet[key][1]
        #  Construct the header in csv format (first row of the file)
        headers = b",".join([HistorySet[key][1]['outputSpaceHeaders'][i] for i in
                             range(len(attributes['outputSpaceHeaders']))])
        #  Construct history name
        hist = key
        #  If file, split the strings and add the working directory if present
        if self.workingDir:
          output.setPath(self.workingDir)
          # original if os.path.split(output.getAbsFile())[1] == '': output.setAbsFile(output.getAbsFile()[:-1])
          # I don't think this applies anymore # if output.getFilename() == '': output.setAbsFile(output.getAbsFile()[:-1])
          #splitted_1 = (output.getPath,output.getFilename() #os.path.split(output.getAbsFile())
          #output.setAbsFile(splitted_1[1])
        #splitted = output.getAbsFile().split('.')
        #  Create csv files
        addfile = Files.returnInstance('CSV',self)
        csvfile = Files.returnInstance('CSV',self)
        addfilename = output.getBase() + '_additional_info_' + hist + '.' + output.getExt()
        csvfilename = output.getBase() + '_'                 + hist + '.' + output.getExt()
        addfile.initialize(addfilename,self.messageHandler,output.getPath(),subtype='AdditionalInfo')
        csvfile.initialize(csvfilename,self.messageHandler,output.getPath(),subtype='AdditionalInfo')
        #  Check if workingDir is present and in case join the two paths
        if self.workingDir:
          addfile.setPath(os.path.join(self.workingDir,addfile.getPath()))
          csvfile.setPath(os.path.join(self.workingDir,csvfile.getPath()))

        #  Save the data
        csvfile.open('w')
        addfile.open('w')
        #  Add history to the csv file
        np.savetxt(csvfile, HistorySet[key][0], delimiter = ",", header = utils.toString(headers))
        csvfile.write(os.linesep)
        #  process the attributes in a different csv file (different kind of informations)
        #  Add metadata to additional info csv file
        addfile.write('# History Metadata, ' + os.linesep)
        addfile.write('# ______________________________,' + '_' * len(key) + ',' + os.linesep)
        addfile.write('#number of parameters,' + os.linesep)
        addfile.write(str(attributes['nParams']) + ',' + os.linesep)
        addfile.write('#parameters,' + os.linesep)
        addfile.write(headers + os.linesep)
        addfile.write('#parentID,' + os.linesep)
        addfile.write(attributes['parentID'] + os.linesep)
        addfile.write('#start time,' + os.linesep)
        addfile.write(str(attributes['startTime']) + os.linesep)
        addfile.write('#end time,' + os.linesep)
        addfile.write(str(attributes['end_time']) + os.linesep)
        addfile.write('#number of time-steps,' + os.linesep)
        addfile.write(str(attributes['nTimeSteps']) + os.linesep)
        addfile.write(os.linesep)
    else: self.raiseAnError(NotImplementedError, 'for input type ' + self.inObj.type + ' not yet implemented.')

  def run(self, Input):  # inObj,workingDir=None):
    """
     This method executes the postprocessor action. In this case, it just returns the input
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, object, the input
    """
    return Input[-1]
#
#
#
class BasicStatistics(BasePostProcessor):
  """
    BasicStatistics filter class. It computes all the most popular statistics
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.parameters = {}  # parameters dictionary (they are basically stored into a dictionary identified by tag "targets"
    self.acceptedCalcParam = ['covariance', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity', 'pearson', 'expectedValue', 'sigma', 'variationCoefficient', 'variance', 'skewness', 'kurtosis', 'median', 'percentile']  # accepted calculation parameters
    self.what = self.acceptedCalcParam  # what needs to be computed... default...all
    self.methodsToRun = []  # if a function is present, its outcome name is here stored... if it matches one of the known outcomes, the pp is going to use the function to compute it
    self.externalFunction = []
    self.printTag = 'POSTPROCESSOR BASIC STATISTIC'
    self.requiredAssObject = (True, (['Function'], [-1]))
    self.biased = False
    self.sampled = {}
    self.calculated = {}

  def inputToInternal(self, currentInp):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, inputDict, dictionary of the converted data
    """
    # each post processor knows how to handle the coming inputs. The BasicStatistics postprocessor accept all the input type (files (csv only), hdf5 and datas
    if type(currentInp) == list  : currentInput = currentInp [-1]
    else                         : currentInput = currentInp
    if type(currentInput) == dict:
      if 'targets' in currentInput.keys(): return currentInput
    inputDict = {'targets':{}, 'metadata':{}}
    if hasattr(currentInput,'type'):
      inType = currentInput.type
    else:
      if type(currentInput).__name__ == 'list'    : inType = 'list'
      else: self.raiseAnError(IOError, self, 'BasicStatistics postprocessor accepts files,HDF5,Data(s) only! Got ' + str(type(currentInput)))
    if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(inType,Files.File):
      self.raiseAnError(IOError, self, 'BasicStatistics postprocessor accepts files,HDF5,Data(s) only! Got ' + str(inType) + '!!!!')
    if isinstance(inType,Files.File):
      if currentInput.subtype == 'csv': pass
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
          self.sampled[targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
          self.calculated[targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
      # now we check if the sampler that genereted the samples are from adaptive... in case... create the grid
      if 'SamplerType' in inputDict['metadata'].keys(): pass

    return inputDict

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the BasicStatistic pp. In here the working dir is
     grepped.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "what":
        self.what = child.text
        if self.what == 'all': self.what = self.acceptedCalcParam
        else:
          toCompute = []
          for whatc in self.what.split(','):
            toCompute.append(whatc.strip())
            if whatc not in self.acceptedCalcParam:
              if whatc.split("_")[0] != 'percentile':self.raiseAnError(IOError, 'BasicStatistics postprocessor asked unknown operation ' + whatc + '. Available ' + str(self.acceptedCalcParam))
              else:
                # check if the percentile is correct
                requestedPercentile = whatc.split("_")[-1]
                integerPercentile = utils.intConversion(requestedPercentile.replace("%",""))
                if integerPercentile is None: self.raiseAnError(IOError,"Could not convert the inputted percentile. The percentile needs to an integer between 1 and 100. Got "+requestedPercentile)
                floatPercentile = utils.floatConversion(requestedPercentile.replace("%",""))
                if floatPercentile < 1.0 or floatPercentile > 100.0: self.raiseAnError(IOError,"the percentile needs to an integer between 1 and 100. Got "+str(floatPercentile))
                if -float(integerPercentile)/floatPercentile + 1.0 > 0.0001: self.raiseAnError(IOError,"the percentile needs to an integer between 1 and 100. Got "+str(floatPercentile))
          self.what = toCompute
      if child.tag == "parameters"   : self.parameters['targets'] = child.text.split(',')
      if child.tag == "methodsToRun" : self.methodsToRun = child.text.split(',')
      if child.tag == "biased"       :
          if child.text.lower() in utils.stringsThatMeanTrue(): self.biased = True
      assert (self.parameters is not []), self.raiseAnError(IOError, 'I need parameters to work on! Please check your input for PP: ' + self.name)

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    # output
    parameterSet = list(set(list(self.parameters['targets'])))
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, ' No available Output to collect (Run probabably is not finished yet)')
    outputDict = finishedjob.returnEvaluation()[1]
    methodToTest = []
    for key in self.methodsToRun:
      if key not in self.acceptedCalcParam: methodToTest.append(key)
    if isinstance(output,Files.File):
      availextens = ['csv', 'txt']
      outputextension = output.getExt().lower() #split('.')[-1].lower()
      if outputextension not in availextens:
        self.raiseAWarning('BasicStatistics postprocessor output extension you input is ' + outputextension)
        self.raiseAWarning('Available are ' + str(availextens) + '. Convertint extension to ' + str(availextens[0]) + '!')
        outputextension = availextens[0]
        output.setExtension(outputextension)
      if outputextension != 'csv': separator = ' '
      else                       : separator = ','
      output.setPath(self.__workingDir)#, output.base)#output[:output.rfind('.')] + '.' + outputextension)
      self.raiseADebug('Dumping output in file named ' + output.getAbsFile())
      output.open('w')
      output.write('ComputedQuantities'+separator+separator.join(parameterSet) + os.linesep)
      quantitiesToWrite = {}
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          if what not in quantitiesToWrite.keys():quantitiesToWrite[what] = []
          for targetP in parameterSet:
            quantitiesToWrite[what].append('%.8E' % copy.deepcopy(outputDict[what][targetP]))
          output.write(what + separator +  separator.join(quantitiesToWrite[what])+os.linesep)
      maxLength = max(len(max(parameterSet, key = len)) + 5, 16)
      for what in outputDict.keys():
        if what in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity']:
          self.raiseADebug('Writing parameter matrix ' + what)
          output.write(os.linesep)
          output.write(what + os.linesep)
          if outputextension != 'csv': output.write(' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep)
          else                       : output.write('matrix' + separator + ''.join([str(item) + separator for item in parameterSet]) + os.linesep)
          for index in range(len(parameterSet)):
            if outputextension != 'csv': output.write(parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict[what][index]]) + os.linesep)
            else                       : output.write(parameterSet[index] + ''.join([separator + '%.8E' % item for item in outputDict[what][index]]) + os.linesep)
        if what == 'sensitivity':
          if not self.sampled: self.raiseAWarning('No sampled Input variable defined in ' + str(self.name) + ' PP. The I/O Sensitivity Matrix wil not be calculated.')
          else:
            output.write(os.linesep)
            self.raiseADebug('Writing parameter matrix ' + what)
            output.write(what + os.linesep)
            calculatedSet = list(set(list(self.calculated)))
            sampledSet = list(set(list(self.sampled)))
            if outputextension != 'csv': output.write(' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in sampledSet]) + os.linesep)
            else                       : output.write('matrix' + separator + ''.join([str(item) + separator for item in sampledSet]) + os.linesep)
            for index in range(len(calculatedSet)):
              if outputextension != 'csv': output.write(calculatedSet[index] + ' ' * (maxLength - len(calculatedSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict[what][index]]) + os.linesep)
              else                       :
                output.write(calculatedSet[index] + ''.join([separator + '%.8E' % item for item in outputDict[what][index]]) + os.linesep)
      if self.externalFunction:
        self.raiseADebug('Writing External Function results')
        output.write(os.linesep + 'EXT FUNCTION ' + os.linesep)
        output.write(os.linesep)
        for what in self.methodsToRun:
          if what not in self.acceptedCalcParam:
            self.raiseADebug('Writing External Function parameter ' + what)
            output.write(what + separator + '%.8E' % outputDict[what] + os.linesep)
    elif output.type in ['PointSet','Point','History','HistorySet']:
      self.raiseADebug('Dumping output in data object named ' + output.name)
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          for targetP in parameterSet:
            self.raiseADebug('Dumping variable ' + targetP + '. Parameter: ' + what + '. Metadata name = ' + targetP + '-' + what)
            output.updateMetadata(targetP + '-' + what, outputDict[what][targetP])
        else:
          if what not in methodToTest:
            self.raiseADebug('Dumping matrix ' + what + '. Metadata name = ' + what + '. Targets stored in ' + 'targets-' + what)
            output.updateMetadata('targets-' + what, parameterSet)
            output.updateMetadata(what.replace("|","-"), outputDict[what])
      if self.externalFunction:
        self.raiseADebug('Dumping External Function results')
        for what in self.methodsToRun:
          if what not in self.acceptedCalcParam:
            output.updateMetadata(what, outputDict[what])
            self.raiseADebug('Dumping External Function parameter ' + what)
    elif output.type == 'HDF5' : self.raiseAWarning('Output type ' + str(output.type) + ' not yet implemented. Skip it !!!!!')
    else: self.raiseAnError(IOError, 'Output type ' + str(output.type) + ' unknown.')


  def __computeVp(self,p,weights):
    """
     Compute the sum of p-th power of weights
     @ In, p, int, the power
     @ In, weights, array-like, weights
     @ Out, sum, float, the sum of p-th power of weights
    """
    return np.sum(np.power(weights,p))

  def __computeUnbiasedCorrection(self,order,weightsOrN):
    """
     Compute unbiased correction given weights and momement order
     Reference paper:
     Lorenzo Rimoldini, "Weighted skewness and kurtosis unbiased by sample size", http://arxiv.org/pdf/1304.6564.pdf
     @ In, order, int, moment order
     @ In, weightsOrN, array-like or int, if array-like -> weights else -> number of samples
     @ Out, corrFactor, float (order <=3) or tuple of floats (order ==4), the unbiased correction factor
    """
    if order > 4: self.raiseAnError(RuntimeError,"computeUnbiasedCorrection is implemented for order <=4 only!")
    if type(weightsOrN).__name__ not in ['int','int8','int16','int64','int32']:
      if order == 2:
        V1, v1Square, V2 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**2.0, self.__computeVp(2, weightsOrN)
        corrFactor   = v1Square/(v1Square-V2)
      elif order == 3:
        V1, v1Cubic, V2, V3 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**3.0, self.__computeVp(2, weightsOrN), self.__computeVp(3, weightsOrN)
        corrFactor   =  v1Cubic/(v1Cubic-3.0*V2*V1+2.0*V3)
      elif order == 4:
        V1, v1Square, V2, V3, V4 = self.__computeVp(1, weightsOrN), self.__computeVp(1, weightsOrN)**2.0, self.__computeVp(2, weightsOrN), self.__computeVp(3, weightsOrN), self.__computeVp(4, weightsOrN)
        numer1 = v1Square*(v1Square**2.0-3.0*v1Square*V2+2.0*V1*V3+3.0*V2**2.0-3.0*V4)
        numer2 = 3.0*v1Square*(2.0*v1Square*V2-2.0*V1*V3-3.0*V2**2.0+3.0*V4)
        denom = (v1Square-V2)*(v1Square**2.0-6.0*v1Square*V2+8.0*V1*V3+3.0*V2**2.0-6.0*V4)
        corrFactor = numer1/denom ,numer2/denom
    else:
      if   order == 2: corrFactor   = float(weightsOrN)/(float(weightsOrN)-1.0)
      elif order == 3: corrFactor   = (float(weightsOrN)**2.0)/((float(weightsOrN)-1)*(float(weightsOrN)-2))
      elif order == 4: corrFactor = (float(weightsOrN)*(float(weightsOrN)**2.0-2.0*float(weightsOrN)+3.0))/((float(weightsOrN)-1)*(float(weightsOrN)-2)*(float(weightsOrN)-3)),(3.0*float(weightsOrN)*(2.0*float(weightsOrN)-3.0))/((float(weightsOrN)-1)*(float(weightsOrN)-2)*(float(weightsOrN)-3))
    return corrFactor

  def _computeKurtosis(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the Kurtosis (fisher) of an array of observations
      @ In, arrayIn, array-like, the array of values from which the Kurtosis needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the Kurtosis of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(4,pbWeight) if not self.biased else 1.0
      if not self.biased: result = -3.0 + ((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,4.0),pbWeight))*unbiasCorr[0]-unbiasCorr[1]*np.power(((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,2.0),pbWeight))),2.0))/np.power(self._computeVariance(arrayIn,expValue,pbWeight),2.0)
      else              : result = -3.0 + ((1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,4.0),pbWeight))*unbiasCorr)/np.power(self._computeVariance(arrayIn,expValue,pbWeight),2.0)
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(4,len(arrayIn)) if not self.biased else 1.0
      if not self.biased: result = -3.0 + ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**4)*unbiasCorr[0]-unbiasCorr[1]*(np.average((arrayIn - expValue)**2))**2.0)/(self._computeVariance(arrayIn,expValue))**2.0
      else              : result = -3.0 + ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**4)*unbiasCorr)/(self._computeVariance(arrayIn,expValue))**2.0
    return result

  def _computeSkewness(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the skewness of an array of observations
      @ In, arrayIn, array-like, the array of values from which the skewness needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the skewness of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(3,pbWeight) if not self.biased else 1.0
      result = (1.0/self.__computeVp(1,pbWeight))*np.sum(np.dot(np.power(arrayIn - expValue,3.0),pbWeight))*unbiasCorr/np.power(self._computeVariance(arrayIn,expValue,pbWeight),1.5)
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(3,len(arrayIn)) if not self.biased else 1.0
      result = ((1.0/float(len(arrayIn)))*np.sum((arrayIn - expValue)**3)*unbiasCorr)/np.power(self._computeVariance(arrayIn,expValue,pbWeight),1.5)
    return result

  def _computeVariance(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the Variance (fisher) of an array of observations
      @ In, arrayIn, array-like, the array of values from which the Variance needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, result, float, the Variance of the array of data
    """
    if pbWeight is not None:
      unbiasCorr = self.__computeUnbiasedCorrection(2,pbWeight) if not self.biased else 1.0
      result = (1.0/self.__computeVp(1,pbWeight))*np.average((arrayIn - expValue)**2,weights= pbWeight)*unbiasCorr
    else:
      unbiasCorr = self.__computeUnbiasedCorrection(2,len(arrayIn)) if not self.biased else 1.0
      result = np.average((arrayIn - expValue)**2)*unbiasCorr
    return result

  def _computeSigma(self,arrayIn,expValue,pbWeight=None):
    """
      Method to compute the sigma of an array of observations
      @ In, arrayIn, array-like, the array of values from which the sigma needs to be estimated
      @ In, expValue, float, expected value of arrayIn
      @ In, pbWeight, array-like, optional, the reliability weights that correspond to the values in 'array'. If not present, an unweighted approach is used
      @ Out, sigma, float, the sigma of the array of data
    """
    return np.sqrt(self._computeVariance(arrayIn,expValue,pbWeight))

  def _computeWeightedPercentile(self,arrayIn,pbWeight,percent=0.5):
    """
      Method to compute the weighted percentile in a array of data
      @ In, arrayIn, array-like, the array of values from which the percentile needs to be estimated
      @ In, pbWeight, array-like, the reliability weights that correspond to the values in 'array'
      @ In, percent, float, the percentile that needs to be computed (between 0.01 and 1.0)
      @ Out, result, float, the percentile
    """
    idxs                   = np.argsort(np.asarray(zip(pbWeight,arrayIn))[:,1])
    sortedWeightsAndPoints = np.asarray(zip(pbWeight[idxs],arrayIn[idxs]))
    weightsCDF             = np.cumsum(sortedWeightsAndPoints[:,0])
    percentileFunction     = interpolate.interp1d(weightsCDF,[i for i in range(len(arrayIn))],kind='nearest')
    try:
      index  = int(percentileFunction(percent))
      result = sortedWeightsAndPoints[index,1]
    except ValueError:
      result = np.median(arrayIn)
    return result

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case, it computes all the requested statistical FOMs
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, dictionary, Dictionary containing the results
    """
    Input = self.inputToInternal(InputIn)
    outputDict = {}
    pbWeights, pbPresent  = {'realization':None}, False
    if self.externalFunction:
      # there is an external function
      for what in self.methodsToRun:
        outputDict[what] = self.externalFunction.evaluate(what, Input['targets'])
        # check if "what" corresponds to an internal method
        if what in self.acceptedCalcParam:
          if what not in ['pearson', 'covariance', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity']:
            if type(outputDict[what]) != dict: self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a dictionary!!')
          else:
            if type(outputDict[what]) != np.ndarray: self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a numpy.ndarray!!')
            if len(outputDict[what].shape) != 2:     self.raiseAnError(IOError, 'BasicStatistics postprocessor: You have overwritten the "' + what + '" method through an external function, it must be a 2D numpy.ndarray!!')
    # setting some convenience values
    parameterSet = list(set(list(self.parameters['targets'])))  # @Andrea I am using set to avoid the test: if targetP not in outputDict[what].keys()
    if 'metadata' in Input.keys(): pbPresent = 'ProbabilityWeight' in Input['metadata'].keys() if 'metadata' in Input.keys() else False
    if not pbPresent:
      if 'metadata' in Input.keys():
        if 'SamplerType' in Input['metadata'].keys():
          if Input['metadata']['SamplerType'][0] != 'MC' : self.raiseAWarning('BasicStatistics postprocessor can not compute expectedValue without ProbabilityWeights. Use unit weight')
        else: self.raiseAWarning('BasicStatistics can not compute expectedValue without ProbabilityWeights. Use unit weight')
      pbWeights['realization'] = np.asarray([1.0 / len(Input['targets'][self.parameters['targets'][0]])]*len(Input['targets'][self.parameters['targets'][0]]))
    else: pbWeights['realization'] = Input['metadata']['ProbabilityWeight']/np.sum(Input['metadata']['ProbabilityWeight'])
#   This section should take the probability weight for each sampling variable
    pbWeights['SampledVarsPbWeight'] = {'SampledVarsPbWeight':{}}
    if 'metadata' in Input.keys():
      for target in parameterSet:
        if 'ProbabilityWeight-'+target in Input['metadata'].keys():
          pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target] = np.asarray(Input['metadata']['ProbabilityWeight-'+target])
          pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target][:] = pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target][:]/np.sum(pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target])
    # if here because the user could have overwritten the method through the external function
    if 'expectedValue' not in outputDict.keys(): outputDict['expectedValue'] = {}
    expValues = np.zeros(len(parameterSet))
    for myIndex, targetP in enumerate(parameterSet):
      if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
      else        : relWeight  = None
      if relWeight is None: outputDict['expectedValue'][targetP] = np.mean(Input['targets'][targetP])
      else                : outputDict['expectedValue'][targetP] = np.average(Input['targets'][targetP], weights = relWeight)
      expValues[myIndex] = outputDict['expectedValue'][targetP]
    for what in self.what:
      if what not in outputDict.keys(): outputDict[what] = {}
      # sigma
      if what == 'sigma':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeSigma(Input['targets'][targetP],expValues[myIndex],relWeight)
          if (outputDict[what][targetP] == 0):
            self.raiseAWarning('The variable: ' + targetP + ' is not dispersed (sigma = 0)! Please check your input in PP: ' + self.name)
            outputDict[what][targetP] = np.Infinity
      # variance
      if what == 'variance':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
          if (outputDict[what][targetP] == 0):
            self.raiseAWarning('The variable: ' + targetP + ' has zero variance! Please check your input in PP: ' + self.name)
            outputDict[what][targetP] = np.Infinity
      # coefficient of variation (sigma/mu)
      if what == 'variationCoefficient':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          sigma = self._computeSigma(Input['targets'][targetP],expValues[myIndex],relWeight)
          if (outputDict['expectedValue'][targetP] == 0):
            self.raiseAWarning('Expected Value for ' + targetP + ' is zero! Variation Coefficient can not be calculated in PP: ' + self.name)
            outputDict['expectedValue'][targetP] = np.Infinity
          outputDict[what][targetP] = sigma / outputDict['expectedValue'][targetP]
      # kurtosis
      if what == 'kurtosis':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeKurtosis(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
      # skewness
      if what == 'skewness':
        for myIndex, targetP in enumerate(parameterSet):
          if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          else        : relWeight  = None
          outputDict[what][targetP] = self._computeSkewness(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
      # median
      if what == 'median':
        if pbPresent:
          for targetP in parameterSet:
            relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
            outputDict[what][targetP] = self._computeWeightedPercentile(Input['targets'][targetP],relWeight,percent=0.5)
        else:
          for targetP in parameterSet: outputDict[what][targetP] = np.median(Input['targets'][targetP])
      # percentile
      if what.split("_")[0] == 'percentile':
        outputDict.pop(what)
        if "_" not in what: whatPercentile = [what + '_5', what + '_95']
        else              : whatPercentile = [what.replace("%","")]
        for whatPerc in whatPercentile:
          if whatPerc not in outputDict.keys(): outputDict[whatPerc] = {}
          for targetP in self.parameters['targets'  ]:
            if targetP not in outputDict[whatPerc].keys() :
              if pbPresent: relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
              integerPercentile             = utils.intConversion(whatPerc.split("_")[-1].replace("%",""))
              outputDict[whatPerc][targetP] = np.percentile(Input['targets'][targetP], integerPercentile) if not pbPresent else self._computeWeightedPercentile(Input['targets'][targetP],relWeight,percent=float(integerPercentile)/100.0)
      # cov matrix
      if what == 'covariance':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        outputDict[what] = self.covariance(feat, weights = pbWeights['realization'])
      # pearson matrix
      if what == 'pearson':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        outputDict[what] = self.corrCoeff(feat, weights = pbWeights['realization'])  # np.corrcoef(feat)
      # sensitivity matrix
      if what == 'sensitivity':
        if self.sampled:
          self.SupervisedEngine = {}  # dict of ROM instances (== number of targets => keys are the targets)
          for target in self.calculated:
            self.SupervisedEngine[target] = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'linear_model|LinearRegression',
                                                                                                      'Features':','.join(self.sampled.keys()),
                                                                                                      'Target':target})
            relWeight  = pbWeights['realization'] if target not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][target]
            var = self._computeVariance(Input['targets'][target],expValues[parameterSet.index(target)],pbWeight=relWeight)
            if (var == 0): self.raiseAWarning('Sensitivity of a variable (' + target + ') with 0 variance is requested! in PP: ' + self.name)
            else         : self.SupervisedEngine[target].train(Input['targets'])
          for myIndex in range(len(self.calculated.keys())):
            if self.SupervisedEngine[self.calculated.keys()[myIndex]].amITrained:
              outputDict[what][myIndex] = self.SupervisedEngine[self.calculated.keys()[myIndex]].ROM.coef_
              features = self.sampled.keys()
              for index, targetP in enumerate(features):
                relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
                sigma = self._computeSigma(Input['targets'][targetP],expValues[parameterSet.index(targetP)],relWeight)
                outputDict[what][myIndex][index] = outputDict[what][myIndex][index] / sigma
            else:
              value = np.zeros(len(self.calculated.keys()))
              for i in range(len(self.calculated.keys())): value[i] = np.Infinity
              outputDict[what][myIndex] = value
      # VarianceDependentSensitivity matrix
      if what == 'VarianceDependentSensitivity':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        covMatrix = self.covariance(feat, weights = pbWeights['realization'])
        variance = np.zeros(len(list(parameterSet)))
        for myIndex, targetP in enumerate(parameterSet):
          relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          variance[myIndex] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
        for myIndex in range(len(parameterSet)):
          if (variance[myIndex] == 0):
             self.raiseAWarning('Variance for the parameter: ' + parameterSet[myIndex] + ' is zero!...in PP: ' + self.name)
             variance[myIndex] = np.Infinity
          outputDict[what][myIndex] = covMatrix[myIndex, :] / (variance[myIndex])
      # Normalized sensitivity matrix: linear regression slopes normalized by the mean (% change)/(% change)
      if what == 'NormalizedSensitivity':
        feat = np.zeros((len(Input['targets'].keys()), utils.first(Input['targets'].values()).size))
        for myIndex, targetP in enumerate(parameterSet): feat[myIndex, :] = Input['targets'][targetP][:]
        covMatrix = self.covariance(feat, weights = pbWeights['realization'])
        variance = np.zeros(len(list(parameterSet)))
        for myIndex, targetP in enumerate(parameterSet):
          relWeight  = pbWeights['realization'] if targetP not in pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'].keys() else pbWeights['SampledVarsPbWeight']['SampledVarsPbWeight'][targetP]
          variance[myIndex] = self._computeVariance(Input['targets'][targetP],expValues[myIndex],pbWeight=relWeight)
          if (variance[myIndex] is 0):
            self.raiseAWarning('Variance for the parameter: ' + parameterSet[myIndex] + ' is zero!...in PP: ' + self.name)
            variance[myIndex] = np.Infinity
        for myIndex in range(len(parameterSet)):
          outputDict[what][myIndex] = ((covMatrix[myIndex, :] / variance) * expValues) / expValues[myIndex]

    # print on screen
    self.raiseADebug('BasicStatistics ' + str(self.name) + 'pp outputs')
    methodToTest = []
    for key in self.methodsToRun:
      if key not in self.acceptedCalcParam: methodToTest.append(key)
    msg = os.linesep
    for targetP in parameterSet:
      msg += '        *************' + '*' * len(targetP) + '***' + os.linesep
      msg += '        * Variable * ' + targetP + '  *' + os.linesep
      msg += '        *************' + '*' * len(targetP) + '***' + os.linesep
      for what in outputDict.keys():
        if what not in ['covariance', 'pearson', 'NormalizedSensitivity', 'VarianceDependentSensitivity', 'sensitivity'] + methodToTest:
          msg += '               ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
          msg += '               ' + '* ' + what + ' * ' + '%.8E' % outputDict[what][targetP] + '  *' + os.linesep
          msg += '               ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
    maxLength = max(len(max(parameterSet, key = len)) + 5, 16)
    if 'covariance' in outputDict.keys():
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + '*         Covariance        *' + os.linesep
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['covariance'][index]]) + os.linesep
    if 'pearson' in outputDict.keys():
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + '*    Pearson/Correlation    *' + os.linesep
      msg += ' ' * maxLength + '*****************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['pearson'][index]]) + os.linesep
    if 'VarianceDependentSensitivity' in outputDict.keys():
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + '*VarianceDependentSensitivity*' + os.linesep
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['VarianceDependentSensitivity'][index]]) + os.linesep
    if 'NormalizedSensitivity' in outputDict.keys():
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + '* Normalized V.D.Sensitivity *' + os.linesep
      msg += ' ' * maxLength + '******************************' + os.linesep
      msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in parameterSet]) + os.linesep
      for index in range(len(parameterSet)):
        msg += parameterSet[index] + ' ' * (maxLength - len(parameterSet[index])) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['NormalizedSensitivity'][index]]) + os.linesep
    if 'sensitivity' in outputDict.keys():
      if not self.sampled: self.raiseAWarning('No sampled Input variable defined in ' + str(self.name) + ' PP. The I/O Sensitivity Matrix wil not be calculated.')
      else:
        msg += ' ' * maxLength + '*****************************' + os.linesep
        msg += ' ' * maxLength + '*    I/O   Sensitivity      *' + os.linesep
        msg += ' ' * maxLength + '*****************************' + os.linesep
        msg += ' ' * maxLength + ''.join([str(item) + ' ' * (maxLength - len(item)) for item in self.sampled]) + os.linesep
        sigma = {}
        for indexCalculated in range(len(self.calculated.keys())):
          #variable = self.sampled.keys()[indexSampled]
          msg += self.calculated.keys()[indexCalculated] + ' ' * (maxLength) + ''.join(['%.8E' % item + ' ' * (maxLength - 14) for item in outputDict['sensitivity'][indexCalculated]]) + os.linesep

    if self.externalFunction:
      msg += ' ' * maxLength + '+++++++++++++++++++++++++++++' + os.linesep
      msg += ' ' * maxLength + '+ OUTCOME FROM EXT FUNCTION +' + os.linesep
      msg += ' ' * maxLength + '+++++++++++++++++++++++++++++' + os.linesep
      for what in self.methodsToRun:
        if what not in self.acceptedCalcParam:
          msg += '              ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
          msg += '              ' + '* ' + what + ' * ' + '%.8E' % outputDict[what] + '  *' + os.linesep
          msg += '              ' + '**' + '*' * len(what) + '***' + 6 * '*' + '*' * 8 + '***' + os.linesep
    self.raiseADebug(msg)
    return outputDict

  def covariance(self, feature, weights = None, rowvar = 1):
      """
        This method calculates the covariance Matrix for the given data.
        Unbiased unweighted covariance matrix, weights is None, bias is 0 (default)
        Biased unweighted covariance matrix,   weights is None, bias is 1
        Unbiased weighted covariance matrix,   weights is not None, bias is 0
        Biased weighted covariance matrix,     weights is not None, bias is 1
        can be calcuated depending on the selection of the inputs.
        @ In,  feature, array-like, [#targets,#samples]  features' samples
        @ In,  weights, array-like, optional, [#samples]  reliability weights. Default is None
        @ In,  rowvar, int, optional, If rowvar is non-zero, then each row represents a variable,
                                      with samples in the columns. Otherwise, the relationship is transposed. Default=1
        @ Out, covMatrix, array-like, [#targets,#targets] the covariance matrix
      """
      X = np.array(feature, ndmin = 2, dtype = np.result_type(feature, np.float64))
      diff = np.zeros(feature.shape, dtype = np.result_type(feature, np.float64))
      if weights is not None: w = np.array(weights, ndmin = 1, dtype = np.float64)
      if X.shape[0] == 1: rowvar = 1
      if rowvar:
          N = X.shape[1]
          axis = 0
      else:
          N = X.shape[0]
          axis = 1
      if weights is not None:
          sumWeights = np.sum(weights)
          sumSquareWeights = np.sum(np.square(weights))
          diff = X - np.atleast_2d(np.average(X, axis = 1 - axis, weights = weights)).T
      else:
          diff = X - np.mean(X, axis = 1 - axis, keepdims = True)
      if weights is not None:
          if not self.biased: fact = float(sumWeights / ((sumWeights * sumWeights - sumSquareWeights)))
          else:               fact = float(1.0 / (sumWeights))
      else:
          if not self.biased: fact = float(1.0 / (N - 1))
          else:               fact = float(1.0 / N)
      if fact <= 0:
          warnings.warn("Degrees of freedom <= 0", RuntimeWarning)
          fact = 0.0
      if not rowvar:
        if weights is not None: covMatrix = (np.dot(diff.T, w * diff) * fact).squeeze()
        else:                   covMatrix = (np.dot(diff.T, diff) * fact).squeeze()
      else:
        if weights is not None: covMatrix = (np.dot(w * diff, diff.T) * fact).squeeze()
        else:                   covMatrix = (np.dot(diff, diff.T) * fact).squeeze()
      return covMatrix

  def corrCoeff(self, feature, weights = None, rowvar = 1):
      """
        This method calculates the correlation coefficient Matrix (pearson) for the given data.
        Unbiased unweighted covariance matrix, weights is None, bias is 0 (default)
        Biased unweighted covariance matrix,   weights is None, bias is 1
        Unbiased weighted covariance matrix,   weights is not None, bias is 0
        Biased weighted covariance matrix,     weights is not None, bias is 1
        can be calcuated depending on the selection of the inputs.
        @ In,  feature, array-like, [#targets,#samples]  features' samples
        @ In,  weights, array-like, optional, [#samples]  reliability weights. Default is None
        @ In,  rowvar, int, optional, If rowvar is non-zero, then each row represents a variable,
                                      with samples in the columns. Otherwise, the relationship is transposed. Default=1
        @ Out, corrMatrix, array-like, [#targets,#targets] the correlation matrix
      """
      covM = self.covariance(feature, weights, rowvar)
      try:
        d = np.diag(covM)
        corrMatrix = covM / np.sqrt(np.multiply.outer(d, d))
      except ValueError:  # scalar covariance
        # nan if incorrect value (nan, inf, 0), 1 otherwise
        corrMatrix = covM / covM
      return corrMatrix
#
#
#
class LoadCsvIntoInternalObject(BasePostProcessor):
  """
    LoadCsvIntoInternalObject pp class. It is in charge of loading CSV files into one of the internal object (Data(s) or HDF5)
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.sourceDirectory = None
    self.listOfCsvFiles = []
    self.printTag = 'POSTPROCESSOR LoadCsv'

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the LoadCSV pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']
    if '~' in self.sourceDirectory               : self.sourceDirectory = os.path.expanduser(self.sourceDirectory)
    if not os.path.isabs(self.sourceDirectory)   : self.sourceDirectory = os.path.normpath(os.path.join(self.__workingDir, self.sourceDirectory))
    if not os.path.exists(self.sourceDirectory)  : self.raiseAnError(IOError, "The directory indicated for PostProcessor " + self.name + "does not exist. Path: " + self.sourceDirectory)
    for _dir, _, _ in os.walk(self.sourceDirectory): self.listOfCsvFiles.extend(glob(os.path.join(_dir, "*.csv")))
    if len(self.listOfCsvFiles) == 0             : self.raiseAnError(IOError, "The directory indicated for PostProcessor " + self.name + "does not contain any csv file. Path: " + self.sourceDirectory)
    self.listOfCsvFiles.sort()

  def inputToInternal(self, currentInput):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, list, list of csv files
    """
    return self.listOfCsvFiles

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "directory": self.sourceDirectory = child.text
    if not self.sourceDirectory: self.raiseAnError(IOError, "The PostProcessor " + self.name + "needs a directory for loading the csv files!")

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    for index, csvFile in enumerate(self.listOfCsvFiles):

      attributes = {"prefix":str(index), "inputFile":self.name, "type":"csv", "name":os.path.join(self.sourceDirectory, csvFile)}
      metadata = finishedjob.returnMetadata()
      if metadata:
        for key in metadata: attributes[key] = metadata[key]
      try:                   output.addGroup(attributes, attributes)
      except AttributeError:
        outfile = Files.returnInstance('CSV',self)
        outfile.initialize(csvFile,self.messageHandler,path=self.sourceDirectory)
        output.addOutput(outfile, attributes)
        if metadata:
          for key, value in metadata.items(): output.updateMetadata(key, value, attributes)

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case, it just returns the list of csv files
     @ In,  Input, object, object contained the data to process. (inputToInternal output)
     @ Out, list, list of csv files
    """
    return self.listOfCsvFiles
#
#
#
class LimitSurface(BasePostProcessor):
  """
    LimitSurface filter class. It computes the limit surface associated to a dataset
  """

  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self,messageHandler)
    self.parameters        = {}               #parameters dictionary (they are basically stored into a dictionary identified by tag "targets"
    self.surfPoint         = None             #coordinate of the points considered on the limit surface
    self.testMatrix        = OrderedDict()    #This is the n-dimensional matrix representing the testing grid
    self.gridCoord         = {}               #Grid coordinates
    self.functionValue     = {}               #This a dictionary that contains np vectors with the value for each variable and for the goal function
    self.ROM               = None             #Pointer to a ROM
    self.externalFunction  = None             #Pointer to an external Function
    self.tolerance         = 1.0e-4           #SubGrid tollerance
    self.gridFromOutside   = False            #The grid has been passed from outside (self._initFromDict)?
    self.lsSide            = "negative"       # Limit surface side to compute the LS for (negative,positive,both)
    self.gridEntity        = None
    self.bounds            = None
    self.jobHandler        = None
    self.transfMethods     = {}
    self.requiredAssObject = (True,(['ROM','Function'],[-1,1]))
    self.printTag = 'POSTPROCESSOR LIMITSURFACE'

  def _localWhatDoINeed(self):
    """
    This method is a local mirror of the general whatDoINeed method.
    It is implemented by the samplers that need to request special objects
    @ In , None, None
    @ Out, needDict, list of objects needed
    """
    return {'internal':[(None,'jobHandler')]}

  def _localGenerateAssembler(self,initDict):
    """
    Generates the assembler.
    @ In, initDict, dict of init objects
    @ Out, None
    """
    self.jobHandler = initDict['internal']['jobHandler']

  def inputToInternal(self, currentInp):
    """
     Method to convert an input object into the internal format that is
     understandable by this pp.
     @ In, currentInput, object, an object that needs to be converted
     @ Out, dict, the resulting dictionary containing features and response
    """
    # each post processor knows how to handle the coming inputs. The BasicStatistics postprocessor accept all the input type (files (csv only), hdf5 and datas
    if type(currentInp) == list: currentInput = currentInp[-1]
    else                       : currentInput = currentInp
    if type(currentInp) == dict:
      if 'targets' in currentInput.keys(): return
    inputDict = {'targets':{}, 'metadata':{}}
    #FIXME I don't think this is checking for files, HDF5 and dataobjects
    if hasattr(currentInput,'type'):
      inType = currentInput.type
    else:
      self.raiseAnError(IOError, self, 'LimitSurface postprocessor accepts files,HDF5,Data(s) only! Got ' + str(type(currentInput)))
    if isinstance(currentInp,Files.File):
      if currentInput.subtype == 'csv': pass
      #FIXME else?  This seems like hollow code right now.
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'): inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'): inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
    # to be added
    return inputDict

  def _initializeLSpp(self, runInfo, inputs, initDict):
    """
     Method to initialize the LS post processor (create grid, etc.)
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.gridEntity = GridEntities.returnInstance("MultiGridEntity",self,self.messageHandler)
    self.__workingDir     = runInfo['WorkingDir']
    self.externalFunction = self.assemblerDict['Function'][0][3]
    if 'ROM' not in self.assemblerDict.keys():
      self.ROM = SupervisedLearning.returnInstance('SciKitLearn', self, **{'SKLtype':'neighbors|KNeighborsClassifier',"n_neighbors":1, 'Features':','.join(list(self.parameters['targets'])), 'Target':self.externalFunction.name})
    else: self.ROM = self.assemblerDict['ROM'][0][3]
    self.ROM.reset()
    self.indexes = -1
    for index, inp in enumerate(self.inputs):
      if type(inp).__name__ in ['str', 'bytes', 'unicode']: self.raiseAnError(IOError, 'LimitSurface PostProcessor only accepts Data(s) as inputs!')
      if inp.type in ['PointSet', 'Point']: self.indexes = index
    if self.indexes == -1: self.raiseAnError(IOError, 'LimitSurface PostProcessor needs a Point or PointSet as INPUT!!!!!!')
    else:
      # check if parameters are contained in the data
      inpKeys = self.inputs[self.indexes].getParaKeys("inputs")
      outKeys = self.inputs[self.indexes].getParaKeys("outputs")
      self.paramType = {}
      for param in self.parameters['targets']:
        if param not in inpKeys + outKeys: self.raiseAnError(IOError, 'LimitSurface PostProcessor: The param ' + param + ' not contained in Data ' + self.inputs[self.indexes].name + ' !')
        if param in inpKeys: self.paramType[param] = 'inputs'
        else:                self.paramType[param] = 'outputs'
    if self.bounds == None:
      self.bounds = {"lowerBounds":{},"upperBounds":{}}
      for key in self.parameters['targets']: self.bounds["lowerBounds"][key], self.bounds["upperBounds"][key] = min(self.inputs[self.indexes].getParam(self.paramType[key],key,nodeid = 'RecontructEnding')), max(self.inputs[self.indexes].getParam(self.paramType[key],key,nodeid = 'RecontructEnding'))
    self.gridEntity.initialize(initDictionary={"rootName":self.name,'constructTensor':True, "computeCells":initDict['computeCells'] if 'computeCells' in initDict.keys() else False,
                                               "dimensionNames":self.parameters['targets'], "lowerBounds":self.bounds["lowerBounds"],"upperBounds":self.bounds["upperBounds"],
                                               "volumetricRatio":self.tolerance   ,"transformationMethods":self.transfMethods})
    self.nVar                  = len(self.parameters['targets'])                                  # Total number of variables
    self.axisName              = self.gridEntity.returnParameter("dimensionNames",self.name)      # this list is the implicit mapping of the name of the variable with the grid axis ordering self.axisName[i] = name i-th coordinate
    self.testMatrix[self.name] = np.zeros(self.gridEntity.returnParameter("gridShape",self.name)) # grid where the values of the goalfunction are stored

  def _initializeLSppROM(self, inp, raiseErrorIfNotFound = True):
    """
     Method to initialize the LS accelleration rom
     @ In, inp, Data(s) object, data object containing the training set
     @ In, raiseErrorIfNotFound, bool, throw an error if the limit surface is not found
    """
    self.raiseADebug('Initiate training')
    if type(inp) == dict:
      self.functionValue.update(inp['inputs' ])
      self.functionValue.update(inp['outputs'])
    else:
      self.functionValue.update(inp.getParametersValues('inputs', nodeid = 'RecontructEnding'))
      self.functionValue.update(inp.getParametersValues('outputs', nodeid = 'RecontructEnding'))
    # recovery the index of the last function evaluation performed
    if self.externalFunction.name in self.functionValue.keys(): indexLast = len(self.functionValue[self.externalFunction.name]) - 1
    else                                                      : indexLast = -1
    # index of last set of point tested and ready to perform the function evaluation
    indexEnd = len(self.functionValue[self.axisName[0]]) - 1
    tempDict = {}
    if self.externalFunction.name in self.functionValue.keys():
      self.functionValue[self.externalFunction.name] = np.append(self.functionValue[self.externalFunction.name], np.zeros(indexEnd - indexLast))
    else: self.functionValue[self.externalFunction.name] = np.zeros(indexEnd + 1)

    for myIndex in range(indexLast + 1, indexEnd + 1):
      for key, value in self.functionValue.items(): tempDict[key] = value[myIndex]
      self.functionValue[self.externalFunction.name][myIndex] = self.externalFunction.evaluate('residuumSign', tempDict)
      if abs(self.functionValue[self.externalFunction.name][myIndex]) != 1.0: self.raiseAnError(IOError, 'LimitSurface: the function evaluation of the residuumSign method needs to return a 1 or -1!')
      if type(inp) != dict:
        if self.externalFunction.name in inp.getParaKeys('inputs'): inp.self.updateInputValue (self.externalFunction.name, self.functionValue[self.externalFunction.name][myIndex])
        if self.externalFunction.name in inp.getParaKeys('output'): inp.self.updateOutputValue(self.externalFunction.name, self.functionValue[self.externalFunction.name][myIndex])
      else:
        if self.externalFunction.name in inp['inputs' ].keys(): inp['inputs' ][self.externalFunction.name] = np.concatenate((inp['inputs'][self.externalFunction.name],np.asarray(self.functionValue[self.externalFunction.name][myIndex])))
        if self.externalFunction.name in inp['outputs'].keys(): inp['outputs'][self.externalFunction.name] = np.concatenate((inp['outputs'][self.externalFunction.name],np.asarray(self.functionValue[self.externalFunction.name][myIndex])))
    if np.sum(self.functionValue[self.externalFunction.name]) == float(len(self.functionValue[self.externalFunction.name])) or np.sum(self.functionValue[self.externalFunction.name]) == -float(len(self.functionValue[self.externalFunction.name])):
      if raiseErrorIfNotFound: self.raiseAnError(ValueError, 'LimitSurface: all the Function evaluations brought to the same result (No Limit Surface has been crossed...). Increase or change the data set!')
      else                   : self.raiseAWarning('LimitSurface: all the Function evaluations brought to the same result (No Limit Surface has been crossed...)!')
    #printing----------------------
    self.raiseADebug('LimitSurface: Mapping of the goal function evaluation performed')
    self.raiseADebug('LimitSurface: Already evaluated points and function values:')
    keyList = list(self.functionValue.keys())
    self.raiseADebug(','.join(keyList))
    for index in range(indexEnd + 1):
      self.raiseADebug(','.join([str(self.functionValue[key][index]) for key in keyList]))
    #printing----------------------
    tempDict = {}
    for name in self.axisName: tempDict[name] = np.asarray(self.functionValue[name])
    tempDict[self.externalFunction.name] = self.functionValue[self.externalFunction.name]
    self.ROM.train(tempDict)
    self.raiseADebug('LimitSurface: Training performed')
    self.raiseADebug('LimitSurface: Training finished')

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the LS pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    self._initializeLSpp(runInfo, inputs, initDict)
    self._initializeLSppROM(self.inputs[self.indexes])

  def _initFromDict(self, dictIn):
    """
      Initialize the LS pp from a dictionary (not from xml input).
      This is used when other objects initialize and use the LS pp for internal
      calculations
      @ In, dictIn, dict, dictionary of initialization options
    """
    if "parameters" not in dictIn.keys()             : self.raiseAnError(IOError, 'No Parameters specified in "dictIn" dictionary !!!!')
    if "name"                  in dictIn.keys()      : self.name          = dictIn["name"]
    if type(dictIn["parameters"]).__name__ == "list" : self.parameters['targets'] = dictIn["parameters"]
    else                                             : self.parameters['targets'] = dictIn["parameters"].split(",")
    if "bounds"                in dictIn.keys()      : self.bounds        = dictIn["bounds"]
    if "transformationMethods" in dictIn.keys()      : self.transfMethods = dictIn["transformationMethods"]
    if "verbosity"             in dictIn.keys()      : self.verbosity     = dictIn['verbosity']
    if "side"                  in dictIn.keys()      : self.lsSide        = dictIn["side"]
    if "tolerance"             in dictIn.keys()      : self.tolerance     = float(dictIn["tolerance"])
    if self.lsSide not in ["negative", "positive", "both"]: self.raiseAnError(IOError, 'Computation side can be positive, negative, both only !!!!')

  def getFunctionValue(self):
    """
    Method to get a pointer to the dictionary self.functionValue
    @ In, None
    @ Out, dictionary, self.functionValue
    """
    return self.functionValue

  def getTestMatrix(self, nodeName=None,exceptionGrid=None):
    """
    Method to get a pointer to the testMatrix object (evaluation grid)
    @ In, nodeName, string, optional, which grid node should be returned. If None, the self.name one, If "all", all of theme, else the nodeName
    @ In, exceptionGrid, string, optional, which grid node should should not returned in case nodeName is "all"
    @ Out, ndarray , self.testMatrix
    """
    if nodeName == None  : return self.testMatrix[self.name]
    elif nodeName =="all":
      if exceptionGrid == None: return self.testMatrix
      else:
        returnDict = OrderedDict()
        wantedKeys = list(self.testMatrix.keys())
        wantedKeys.pop(wantedKeys.index(exceptionGrid))
        for key in wantedKeys: returnDict[key] = self.testMatrix[key]
        return returnDict
    else                 : return self.testMatrix[nodeName]

  def _localReadMoreXML(self, xmlNode):
    """
      Function to read the portion of the xml input that belongs to this specialized class
      and initialize some stuff based on the inputs got
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    initDict = {}
    for child in xmlNode: initDict[child.tag] = child.text
    initDict.update(xmlNode.attrib)
    self._initFromDict(initDict)

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'No available Output to collect (Run probably is not finished yet)')
    self.raiseADebug(str(finishedjob.returnEvaluation()))
    limitSurf = finishedjob.returnEvaluation()[1]
    if limitSurf[0] is not None:
      for varName in output.getParaKeys('inputs'):
        for varIndex in range(len(self.axisName)):
          if varName == self.axisName[varIndex]:
            output.removeInputValue(varName)
            for value in limitSurf[0][:, varIndex]: output.updateInputValue(varName, copy.copy(value))
      output.removeOutputValue(self.externalFunction.name)
      for value in limitSurf[1]: output.updateOutputValue(self.externalFunction.name, copy.copy(value))

  def refineGrid(self,refinementSteps=2):
    """
     Method to refine the internal grid based on the limit surface previously computed
     @ In, refinementSteps, int, number of refinement steps
     @ Out, None
    """
    cellIds = self.gridEntity.retrieveCellIds([self.listsurfPointNegative,self.listsurfPointPositive],self.name)
    if self.getLocalVerbosity() == 'debug': self.raiseADebug("Limit Surface cell IDs are: \n"+ " \n".join([str(cellID) for cellID in cellIds]))
    self.raiseAMessage("Number of cells to be refined are "+str(len(cellIds))+". RefinementSteps = "+str(max([refinementSteps,2]))+"!")
    self.gridEntity.refineGrid({"cellIDs":cellIds,"refiningNumSteps":int(max([refinementSteps,2]))})
    for nodeName in self.gridEntity.getAllNodesNames(self.name):
      if nodeName != self.name: self.testMatrix[nodeName] = np.zeros(self.gridEntity.returnParameter("gridShape",nodeName))

  def run(self, InputIn = None, returnListSurfCoord = False, exceptionGrid = None, merge = True):
    """
     This method executes the postprocessor action. In this case it computes the limit surface.
     @ In ,InputIn, dictionary, dictionary of data to process
     @ In ,returnListSurfCoord, boolean, True if listSurfaceCoordinate needs to be returned
     @ Out, dictionary, Dictionary containing the limitsurface
    """
    allGridNames = self.gridEntity.getAllNodesNames(self.name)
    if exceptionGrid != None:
      try   : allGridNames.pop(allGridNames.index(exceptionGrid))
      except: pass
    self.surfPoint, evaluations, listsurfPoint = OrderedDict().fromkeys(allGridNames), OrderedDict().fromkeys(allGridNames) ,OrderedDict().fromkeys(allGridNames)
    for nodeName in allGridNames:
      #if skipMainGrid == True and nodeName == self.name: continue
      self.testMatrix[nodeName] = np.zeros(self.gridEntity.returnParameter("gridShape",nodeName))
      self.gridCoord[nodeName] = self.gridEntity.returnGridAsArrayOfCoordinates(nodeName=nodeName)
      tempDict ={}
      for  varId, varName in enumerate(self.axisName): tempDict[varName] = self.gridCoord[nodeName][:,varId]
      self.testMatrix[nodeName].shape     = (self.gridCoord[nodeName].shape[0])                       #rearrange the grid matrix such as is an array of values
      self.testMatrix[nodeName][:]        = self.ROM.evaluate(tempDict)                               #get the prediction on the testing grid
      self.testMatrix[nodeName].shape     = self.gridEntity.returnParameter("gridShape",nodeName)     #bring back the grid structure
      self.gridCoord[nodeName].shape      = self.gridEntity.returnParameter("gridCoorShape",nodeName) #bring back the grid structure
      self.raiseADebug('LimitSurface: Prediction performed')
      # here next the points that are close to any change are detected by a gradient (it is a pre-screener)
      toBeTested = np.squeeze(np.dstack(np.nonzero(np.sum(np.abs(np.gradient(self.testMatrix[nodeName])), axis = 0))))
      #printing----------------------
      self.raiseADebug('LimitSurface:  Limit surface candidate points')
      if self.getLocalVerbosity() == 'debug':
        for coordinate in np.rollaxis(toBeTested, 0):
          myStr = ''
          for iVar, varnName in enumerate(self.axisName): myStr += varnName + ': ' + str(coordinate[iVar]) + '      '
          self.raiseADebug('LimitSurface: ' + myStr + '  value: ' + str(self.testMatrix[nodeName][tuple(coordinate)]))
      # printing----------------------
      # check which one of the preselected points is really on the limit surface
      nNegPoints, nPosPoints                       =  0, 0
      listsurfPointNegative, listsurfPointPositive = [], []

      if self.lsSide in ["negative", "both"]:
        # it returns the list of points belonging to the limit state surface and resulting in a negative response by the ROM
        listsurfPointNegative = self.__localLimitStateSearch__(toBeTested, -1, nodeName)
        nNegPoints = len(listsurfPointNegative)
      if self.lsSide in ["positive", "both"]:
        # it returns the list of points belonging to the limit state surface and resulting in a positive response by the ROM
        listsurfPointPositive = self.__localLimitStateSearch__(toBeTested, 1, nodeName)
        nPosPoints = len(listsurfPointPositive)
      listsurfPoint[nodeName] = listsurfPointNegative + listsurfPointPositive
      #printing----------------------
      if self.getLocalVerbosity() == 'debug':
        if len(listsurfPoint[nodeName]) > 0: self.raiseADebug('LimitSurface: Limit surface points:')
        for coordinate in listsurfPoint[nodeName]:
          myStr = ''
          for iVar, varnName in enumerate(self.axisName): myStr += varnName + ': ' + str(coordinate[iVar]) + '      '
          self.raiseADebug('LimitSurface: ' + myStr + '  value: ' + str(self.testMatrix[nodeName][tuple(coordinate)]))
      # if the number of point on the limit surface is > than zero than save it
      if len(listsurfPoint[nodeName]) > 0:
        self.surfPoint[nodeName] = np.ndarray((len(listsurfPoint[nodeName]), self.nVar))
        evaluations[nodeName] = np.concatenate((-np.ones(nNegPoints), np.ones(nPosPoints)), axis = 0)
        for pointID, coordinate in enumerate(listsurfPoint[nodeName]):
          self.surfPoint[nodeName][pointID, :] = self.gridCoord[nodeName][tuple(coordinate)]
    if self.name != exceptionGrid: self.listsurfPointNegative, self.listsurfPointPositive = listsurfPoint[self.name][:nNegPoints-1],listsurfPoint[self.name][nNegPoints:]
    if merge == True:
      evals = np.hstack(evaluations.values())
      listsurfPoints = np.hstack(listsurfPoint.values())
      surfPoint = np.hstack(self.surfPoint.values())
      if returnListSurfCoord: return surfPoint, evals, listsurfPoints
      else                  : return surfPoint, evals
    else:
      if returnListSurfCoord: return self.surfPoint, evaluations, listsurfPoint
      else                  : return self.surfPoint, evaluations


  def __localLimitStateSearch__(self, toBeTested, sign, nodeName):
    """
    It returns the list of points belonging to the limit state surface and resulting in
    positive or negative responses by the ROM, depending on whether ''sign''
    equals either -1 or 1, respectively.
    """
    listsurfPoint = []
    gridShape = self.gridEntity.returnParameter("gridShape",nodeName)
    myIdList = np.zeros(self.nVar,dtype=int)
    putIt = np.zeros(self.nVar,dtype=bool)
    for coordinate in np.rollaxis(toBeTested, 0):
      myIdList[:] = coordinate
      putIt[:]    = False
      if self.testMatrix[nodeName][tuple(coordinate)] * sign > 0:
        for iVar in range(self.nVar):
          if coordinate[iVar] + 1 < gridShape[iVar]:
            myIdList[iVar] += 1
            if self.testMatrix[nodeName][tuple(myIdList)] * sign <= 0:
              putIt[iVar] = True
              listsurfPoint.append(copy.copy(coordinate))
              break
            myIdList[iVar] -= 1
            if coordinate[iVar] > 0:
              myIdList[iVar] -= 1
              if self.testMatrix[nodeName][tuple(myIdList)] * sign <= 0:
                putIt[iVar] = True
                listsurfPoint.append(copy.copy(coordinate))
                break
              myIdList[iVar] += 1
      #if len(set(putIt)) == 1 and  list(set(putIt))[0] == True: listsurfPoint.append(copy.copy(coordinate))
    return listsurfPoint
#
#
#

class ExternalPostProcessor(BasePostProcessor):
  """
    ExternalPostProcessor class. It will apply an arbitrary python function to
    a dataset and append each specified function's output to the output data
    object, thus the function should produce a scalar value per row of data. I
    have no idea what happens if the function produces multiple outputs.
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.methodsToRun = []  # A list of strings specifying what
                                        # methods the user wants to compute from
                                        # the external interfaces

    self.externalInterfaces = []  # A list of Function objects that
                                        # hopefully contain definitions for all
                                        # of the methods the user wants

    self.printTag = 'POSTPROCESSOR EXTERNAL FUNCTION'
    self.requiredAssObject = (True, (['Function'], ['n']))

  def inputToInternal(self, currentInp):
    """
      Function to convert the received input into a format this object can
      understand
      @ In, currentInp: Some form of data object or list of data objects handed
                        to the post-processor
      @ Out, An input dictionary this object can process
    """

    if type(currentInp) == dict:
      if 'targets' in currentInp.keys(): return
    currentInput = currentInp
    if type(currentInput) != list: currentInput = [currentInput]
    inputDict = {'targets':{}, 'metadata':{}}
    metadata = []
    for item in currentInput:
      inType = None
      if hasattr(item, 'type')  : inType = item.type
      elif type(item) in [list]: inType = "list"
      if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(item,Files.File):
        self.raiseAWarning(self, 'Input type ' + type(item).__name__ + ' not' + ' recognized. I am going to skip it.')
      elif isinstance(item,Files.File):
        if currentInput.subtype == 'csv': self.raiseAWarning(self, 'Input type ' + inType + ' not yet ' + 'implemented. I am going to skip it.')
      elif inType == 'HDF5':
        # TODO
          self.raiseAWarning(self, 'Input type ' + inType + ' not yet ' + 'implemented. I am going to skip it.')
      elif inType == 'PointSet':
        for param in item.getParaKeys('input') : inputDict['targets'][param] = item.getParam('input', param)
        for param in item.getParaKeys('output'): inputDict['targets'][param] = item.getParam('output', param)
        metadata.append(item.getAllMetadata())
      # Not sure if we need it, but keep a copy of every inputs metadata
      inputDict['metadata'] = metadata

    if len(inputDict['targets'].keys()) == 0: self.raiseAnError(IOError, "No input variables have been found in the input objects!")
    for interface in self.externalInterfaces:
      for _ in self.methodsToRun:
        # The function should reference self and use the same variable names
        # as the xml file
        for param in interface.parameterNames():
          if param not in inputDict['targets']:
            self.raiseAnError(IOError, self, 'variable \"' + param + '\" unknown.' + ' Please verify your external' + ' script (' + interface.functionFile
                                          + ') variables match the data'
                                          + ' available in your dataset.')
    return inputDict

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the External pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']
    for key in self.assemblerDict.keys():
      if 'Function' in key:
        indice = 0
        for _ in self.assemblerDict[key]:
          self.externalInterfaces.append(self.assemblerDict[key][indice][3])
          indice += 1

  def _localReadMoreXML(self, xmlNode):
    """
      Function to grab the names of the methods this post-processor will be
      using
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == 'method':
        methods = child.text.split(',')
        self.methodsToRun.extend(methods)

  def collectOutput(self, finishedJob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedJob.returnEvaluation() == -1:
      # #TODO This does not feel right
      self.raiseAnError(RuntimeError, 'No available Output to collect (Run '
                                       + 'probably did not finish yet)')
    inputList = finishedJob.returnEvaluation()[0]
    outputDict = finishedJob.returnEvaluation()[1]

    if isinstance(output,Files.File):
      self.raiseAWarning('Output type File not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'DataObjects':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'HDF5':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                               + ' yet implemented. I am going to skip it.')
    elif output.type == 'PointSet':
      requestedInput = output.getParaKeys('input')
      requestedOutput = output.getParaKeys('output')
      # # The user can simply ask for a computation that may exist in multiple
      # # interfaces, in that case, we will need to qualify their names for the
      # # output. The names should already be qualified from the outputDict.
      # # However, the user may have already qualified the name, so make sure and
      # # test whether the unqualified name exists in the requestedOutput before
      # # replacing it.
      for key, replacements in outputDict['qualifiedNames'].iteritems():
        if key in requestedOutput:
          requestedOutput.remove(key)
          requestedOutput.extend(replacements)

      # # Grab all data from the outputDict and anything else requested not
      # # present in the outputDict will be copied from the input data.
      # # TODO: User may want to specify which dataset the parameter comes from.
      # #       For now, we assume that if we find more than one an error will
      # #      occur.
      # # FIXME: There is an issue that the data size should be determined before
      # #        entering this loop, otherwise if say a scalar is first added,
      # #        then dataLength will be 1 and everything longer will be placed
      # #        in the Metadata.
      # #        How do we know what size the output data should be?
      dataLength = None
      for key in requestedInput + requestedOutput:
        storeInOutput = True
        value = []
        if key in outputDict:
          value = outputDict[key]
        else:
          foundCount = 0
          if key in requestedInput:
            for inputData in inputList:
              if key in inputData.getParametersValues('input').keys():
                value = inputData.getParametersValues('input')[key]
                foundCount += 1
          else:
            for inputData in inputList:
                if key in inputData.getParametersValues('output').keys():
                  value = inputData.getParametersValues('output')[key]
                  foundCount += 1

          if foundCount == 0:
            self.raiseAnError(IOError, key + ' not found in the input '
                                            + 'object or the computed output '
                                            + 'object.')
          elif foundCount > 1:
            self.raiseAnError(IOError, key + ' is ambiguous since it occurs'
                                            + ' in multiple input objects.')

        # # We need the size to ensure the data size is consistent, but there
        # # is no guarantee the data is not scalar, so this check is necessary
        myLength = 1
        if not hasattr(value, "__iter__"):
          value = [value]
        myLength = len(value)

        if dataLength is None:
          dataLength = myLength
        elif dataLength != myLength:
          self.raiseAWarning('Requested output for ' + key + ' has a'
                                    + ' non-conformant data size ('
                                    + str(dataLength) + ' vs ' + str(myLength)
                                    + '), it is being placed in the metadata.')
          storeInOutput = False

        # # Finally, no matter what, place the requested data somewhere
        # # accessible
        if storeInOutput:
          if key in requestedInput:
            for val in value:
              output.updateInputValue(key, val)
          else:
            for val in value:
              output.updateOutputValue(key, val)
        else:
          if not hasattr(value, "__iter__"):
            value = [value]
          for val in value:
            output.updateMetadata(key, val)

    else: self.raiseAnError(IOError, 'Unknown output type: ' + str(output.type))

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case it performs the action defined int
     the external pp
     @ In , InputIn, dictionary, dictionary of data to process
     @ Out, dictionary, Dictionary containing the post-processed results
    """
    Input = self.inputToInternal(InputIn)
    outputDict = {'qualifiedNames' : {}}
    # # This will map the name to its appropriate interface and method
    # # in the case of a function being defined in two separate files, we
    # # qualify the output by appending the name of the interface from which it
    # # originates
    methodMap = {}

    # # First check all the requested methods are available and if there are
    # # duplicates then qualify their names for the user
    for method in self.methodsToRun:
      matchingInterfaces = []
      for interface in self.externalInterfaces:
        if method in interface.availableMethods():
          matchingInterfaces.append(interface)


      if len(matchingInterfaces) == 0:
        self.raiseAWarning(method + ' not found. I will skip it.')
      elif len(matchingInterfaces) == 1:
        methodMap[method] = (matchingInterfaces[0], method)
      else:
        outputDict['qualifiedNames'][method] = []
        for interface in matchingInterfaces:
          methodName = interface.name + '.' + method
          methodMap[methodName] = (interface, method)
          outputDict['qualifiedNames'][method].append(methodName)

    # # Evaluate the method and add it to the outputDict, also if the method
    # # adjusts the input data, then you should update it as well.
    for methodName, (interface, method) in methodMap.iteritems():
      outputDict[methodName] = interface.evaluate(method, Input['targets'])
      for target in Input['targets']:
        if hasattr(interface, target):
          outputDict[target] = getattr(interface, target)

    return outputDict

#
#
#
#
class TopologicalDecomposition(BasePostProcessor):
  """
    TopologicalDecomposition class - Computes an approximated hierarchical
    Morse-Smale decomposition from an input point cloud consisting of an
    arbitrary number of input parameters and a response value per input point
  """
  def __init__(self, messageHandler):
    """
     Constructor
     @ In, messageHandler, message handler object
    """

    BasePostProcessor.__init__(self, messageHandler)
    self.acceptedGraphParam = ['approximate knn', 'delaunay', 'beta skeleton', \
                               'relaxed beta skeleton']
    self.acceptedPersistenceParam = ['difference','probability','count']#,'area']
    self.acceptedGradientParam = ['steepest', 'maxflow']
    self.acceptedNormalizationParam = ['feature', 'zscore', 'none']

    # Some default arguments
    self.gradient = 'steepest'
    self.graph = 'beta skeleton'
    self.beta = 1
    self.knn = -1
    self.simplification = 0
    self.persistence = 'difference'
    self.normalization = None
    self.weighted = False
    self.parameters = {}

  def inputToInternal(self, currentInp):
    """
      Function to convert the incoming input into a usable format
      @ In, currentInp : The input object to process
      @ Out, None
    """
    if type(currentInp) == list  : currentInput = currentInp [-1]
    else                         : currentInput = currentInp
    if type(currentInput) == dict:
      if 'features' in currentInput.keys(): return currentInput
    inputDict = {'features':{}, 'targets':{}, 'metadata':{}}
    if hasattr(currentInput, 'type'):
      inType = currentInput.type
    elif type(currentInput).__name__ == 'list':
      inType = 'list'
    else:
      self.raiseAnError(IOError, self.__class__.__name__,
                        ' postprocessor accepts files, HDF5, Data(s) only. ',
                        ' Requested: ', type(currentInput))

    if inType not in ['HDF5', 'PointSet', 'list'] and not isinstance(currentInput,Files.File):
      self.raiseAnError(IOError, self, self.__class__.__name__ + ' post-processor only accepts files, HDF5, or DataObjects! Got ' + str(inType) + '!!!!')
    # FIXME: implement this feature
    if isinstance(currentInput,Files.File):
      if currentInput.subtype == 'csv': pass
    # FIXME: implement this feature
    if inType == 'HDF5': pass  # to be implemented
    if inType in ['PointSet']:
      for targetP in self.parameters['features']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['features'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['features'][targetP] = currentInput.getParam('output', targetP)
      for targetP in self.parameters['targets']:
        if   targetP in currentInput.getParaKeys('input'):
          inputDict['targets'][targetP] = currentInput.getParam('input' , targetP)
        elif targetP in currentInput.getParaKeys('output'):
          inputDict['targets'][targetP] = currentInput.getParam('output', targetP)
      inputDict['metadata'] = currentInput.getAllMetadata()
    # now we check if the sampler that genereted the samples are from adaptive... in case... create the grid
    if 'SamplerType' in inputDict['metadata'].keys(): pass
    return inputDict

  def _localReadMoreXML(self, xmlNode):
    """
      Function to grab the names of the methods this post-processor will be
      using
      @ In, xmlNode    : Xml element node
      @ Out, None
    """
    for child in xmlNode:
      if child.tag == "graph":
        self.graph = child.text.encode('ascii').lower()
        if self.graph not in self.acceptedGraphParam:
          self.raiseAnError(IOError, 'Requested unknown graph type: ',
                            self.graph, '. Available options: ',
                            self.acceptedGraphParam)
      elif child.tag == "gradient":
        self.gradient = child.text.encode('ascii').lower()
        if self.gradient not in self.acceptedGradientParam:
          self.raiseAnError(IOError, 'Requested unknown gradient method: ',
                            self.gradient, '. Available options: ',
                            self.acceptedGradientParam)
      elif child.tag == "beta":
        self.beta = float(child.text)
        if self.beta <= 0 or self.beta > 2:
          self.raiseAnError(IOError, 'Requested invalid beta value: ',
                            self.beta, '. Allowable range: (0,2]')
      elif child.tag == 'knn':
        self.knn = int(child.text)
      elif child.tag == 'simplification':
        self.simplification = float(child.text)
      elif child.tag == 'persistence':
        self.persistence = child.text.encode('ascii').lower()
        if self.persistence not in self.acceptedPersistenceParam:
          self.raiseAnError(IOError, 'Requested unknown persistence method: ',
                            self.persistence, '. Available options: ',
                            self.acceptedPersistenceParam)
      elif child.tag == 'parameters':
        self.parameters['features'] = child.text.strip().split(',')
        for i, parameter in enumerate(self.parameters['features']):
          self.parameters['features'][i] = self.parameters['features'][i].encode('ascii')
      elif child.tag == 'weighted':
        self.weighted = child.text in ['True', 'true']
      elif child.tag == 'response':
        self.parameters['targets'] = child.text
      elif child.tag == 'normalization':
        self.normalization = child.text.encode('ascii').lower()
        if self.normalization not in self.acceptedNormalizationParam:
          self.raiseAnError(IOError, 'Requested unknown normalization type: ',
                            self.normalization, '. Available options: ',
                            self.acceptedNormalizationParam)

  def collectOutput(self, finishedJob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob: A JobHandler object that is in charge of running this
                         post-processor
      @ In, output: The object where we want to place our computed results
      @ Out, None
    """
    if finishedJob.returnEvaluation() == -1:
      # TODO This does not feel right
      self.raiseAnError(RuntimeError,'No available output to collect (run probably did not finish yet)')
    inputList = finishedJob.returnEvaluation()[0]
    outputDict = finishedJob.returnEvaluation()[1]

    if type(output).__name__ in ["str", "unicode", "bytes"]:
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'Datas':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'HDF5':
      self.raiseAWarning('Output type ' + type(output).__name__ + ' not'
                         + ' yet implemented. I am going to skip it.')
    elif output.type == 'PointSet':
      requestedInput = output.getParaKeys('input')
      requestedOutput = output.getParaKeys('output')
      dataLength = None
      for inputData in inputList:
        # Pass inputs from input data to output data
        for key, value in inputData.getParametersValues('input').items():
          if key in requestedInput:
            # We need the size to ensure the data size is consistent, but there
            # is no guarantee the data is not scalar, so this check is necessary
            myLength = 1
            if hasattr(value, "__len__"):
              myLength = len(value)

            if dataLength is None:
              dataLength = myLength
            elif dataLength != myLength:
              dataLength = max(dataLength, myLength)
              self.raiseAWarning('Data size is inconsistent. Currently set to '
                                 + str(dataLength) + '.')

            for val in value:
              output.updateInputValue(key, val)

        # Pass outputs from input data to output data
        for key, value in inputData.getParametersValues('output').items():
          if key in requestedOutput:
            # We need the size to ensure the data size is consistent, but there
            # is no guarantee the data is not scalar, so this check is necessary
            myLength = 1
            if hasattr(value, "__len__"):
              myLength = len(value)

            if dataLength is None:
              dataLength = myLength
            elif dataLength != myLength:
              dataLength = max(dataLength, myLength)
              self.raiseAWarning('Data size is inconsistent. Currently set to '
                                      + str(dataLength) + '.')

            for val in value:
              output.updateOutputValue(key, val)

        # Append the min/max labels to the data whether the user wants them or
        # not, and place the hierarchy information into the metadata
        for key, value in outputDict.iteritems():
          if key in ['minLabel', 'maxLabel']:
            output.updateOutputValue(key, [value])
          elif key in ['hierarchy']:
            output.updateMetadata(key, [value])
    else:
      self.raiseAnError(IOError,'Unknown output type:',output.type)

  def run(self, InputIn):
    """
     Function to finalize the filter => execute the filtering
     @ In , dictionary       : dictionary of data to process
     @ Out, dictionary       : Dictionary with results
    """
    # # Possibly load this here in case people have trouble building it, so it
    # # only errors if they try to use it?
    from AMSC_Object import AMSC_Object

    Input = self.inputToInternal(InputIn)
    outputDict = {}

    myDataIn = Input['features']
    myDataOut = Input['targets']
    outputData = myDataOut[self.parameters['targets'].encode('UTF-8')]
    self.pointCount = len(outputData)
    self.dimensionCount = len(self.parameters['features'])

    inputData = np.zeros((self.pointCount, self.dimensionCount))
    for i, lbl in enumerate(self.parameters['features']):
      inputData[:, i] = myDataIn[lbl.encode('UTF-8')]

    if self.weighted:
      weights = InputIn[0].getMetadata('PointProbability')
    else:
      weights = None

    names = self.parameters['features'] + [self.parameters['targets']]
    # FIXME: AMSC_Object employs unsupervised NearestNeighbors algorithm from scikit learn.
    #       The NearestNeighbor algorithm is implemented in SupervisedLearning, which requires features and targets by default.
    #       which we don't have here. When the NearestNeighbor is implemented in unSupervisedLearning switch to it.
    self.__amsc = AMSC_Object(X=inputData, Y=outputData, w=weights,
                              names=names, graph=self.graph,
                              gradient=self.gradient, knn=self.knn,
                              beta=self.beta, normalization=self.normalization,
                              persistence=self.persistence, debug=False)

    self.__amsc.Persistence(self.simplification)
    partitions = self.__amsc.Partitions()

    outputDict['minLabel'] = np.zeros(self.pointCount)
    outputDict['maxLabel'] = np.zeros(self.pointCount)
    output = ""
    for extPair, indices in partitions.iteritems():
      for idx in indices:
        outputDict['minLabel'][idx] = extPair[0]
        outputDict['maxLabel'][idx] = extPair[1]
    outputDict['hierarchy'] = self.__amsc.PrintHierarchy()
    output += '========== Linear Regressors: ==========' + os.linesep
    self.__amsc.BuildModels()
    linearFits = self.__amsc.SegmentFitCoefficients()
    linearFitnesses = self.__amsc.SegmentFitnesses()

    for key in linearFits.keys():
      output += str(key) + os.linesep
      coefficients = linearFits[key]
      rSquared = linearFitnesses[key]
      #output += '\t' + u"\u03B2\u0302: " + str(coefficients) + '\n'
      #output += '\t' + u"R\u00B2: " + str(rSquared) + '\n' + '\n'
      output += '\t' + "beta: " + str(coefficients) + os.linesep
      output += '\t' + "R^2: " + str(rSquared) + 2 * os.linesep
      outputDict['coefficients_%d_%d' % (key[0], key[1])] = coefficients
      outputDict['R2_%d_%d' % (key[0], key[1])] = rSquared

    #output += 'RMSD  = %f\n' % (self.linearNRMSD)
    output += '========== Gaussian Fits: ==========' + os.linesep
    #output += u'a/\u221A(2\u03C0^d|\u03A3|)*e^(-(x-\u03BC)T\u03A3(x-\u03BC)) + c - '
    #      + u'a\t(\u03BC & c are fixed, \u03A3 and a are estimated)\n'
    output += 'a/sqrt(2*(pi)^d|M|)*e^(-(x-mu)TM(x-mu)) + c - a'
    output += '\t(mu & c are fixed, M and a are estimated)' + os.linesep

    exts = linearFits.keys()
    exts = [int(item) for sublist in exts for item in sublist]
    exts = list(set(exts))

    for key in exts:
      output += str(key) + ':' + os.linesep
      (mu, c, a, A) = self.__amsc.GetExtremumFitCoefficients(key)
      #output += u':\t\u03BC=' + str(mu) + '\n'
      output += u':\tmu=' + str(mu) + os.linesep
      output += '\tc=' + str(c) + os.linesep
      output += '\ta=' + str(a) + os.linesep
      output += '\tM=' + os.linesep + str(A) + 2 * os.linesep
      #output += '\t\u03A3=\n' + str(A)+'\n\n'
      #output += '\t' + u"R\u00B2: " + str(rSquared) + '\n\n'

      outputDict['mu_' + str(key)] = mu
      outputDict['c_' + str(key)] = c
      outputDict['a_' + str(key)] = a
      outputDict['Sigma_' + str(key)] = A
      outputDict['R2_' + str(key)] = rSquared

    # output += 'RMSD  = %f and %f\n' % (self.gaussianNRMSD[0],self.gaussianNRMSD[1])
    self.raiseAMessage(output)
    return outputDict

class DataMining(BasePostProcessor):
  """
    DataMiningPostProcessor class. It will apply the specified KDD algorithms in the models
    to a dataset, each specified algorithm's output can be loaded to dataObject.
  """
  def __init__(self, messageHandler):
    """
    Constructor
    @ In, messageHandler, message handler object.
    """
    BasePostProcessor.__init__(self, messageHandler)
    self.printTag = 'POSTPROCESSOR DATAMINING'
    self.algorithms = []  # A list of Algorithms objects that contain definitions for all the algorithms the user wants
    self.requiredAssObject = (True, (['Label'], ['-1']))  # The Label is optional for now....
    self.initializationOptionDict = {}
    self.clusterLabels = None
    self.labelAlgorithms = []
    self.dataObjects = []

  def inputToInternal(self, currentInp):
    """
      Function to convert the received input into a format this object can
      understand
      @ In, currentInp, Some form of data object or list of data objects handed
                        to the post-processor
      @ Out, inputdict, dict, An input dictionary this object can process
    """
    if type(currentInp) == list: currentInput = currentInp[-1]
    else                       : currentInput = currentInp
    if type(currentInp) == dict:
      if 'Features' in currentInput.keys(): return
    inputDict = {'Features':{}, 'parameters':{}, 'Labels':{}, 'metadata':{}}
    if isinstance(currentInp, Files.File):
      if currentInput.subtype == 'csv': self.raiseAnError(IOError, 'CSV File received as an input!')
    if currentInput.type == 'HDF5': self.raiseAnError(IOError, 'HDF5 Object received as an input!')
    if currentInput.type in ['PointSet']:
      if self.initializationOptionDict['KDD']['Features'] == 'input':
        for param in currentInput.getParaKeys('input'): inputDict['Features'][param] = currentInput.getParam('input', param)
      elif self.initializationOptionDict['KDD']['Features'] == 'output':
        for param in currentInput.getParaKeys('output'): inputDict['Features'][param] = currentInput.getParam('output', param)
      elif self.initializationOptionDict['KDD']['Features'] == 'all':
        for param in currentInput.getParaKeys('input') : inputDict['Features'][param] = currentInput.getParam('input', param)
        for param in currentInput.getParaKeys('output'): inputDict['Features'][param] = currentInput.getParam('output', param)
      else:
        features = self.initializationOptionDict['KDD']['Features'].split(',')
        for param in currentInput.getParaKeys('input'):
          if param in features: inputDict['Features'][param] = currentInput.getParam('input', param)
        for param in currentInput.getParaKeys('output'):
          if param in features: inputDict['Features'][param] = currentInput.getParam('output', param)

      inputDict['metadata'] = currentInput.getAllMetadata()


    return inputDict

  def initialize(self, runInfo, inputs, initDict):
    """
     Method to initialize the DataMining pp.
     @ In, runInfo, dict, dictionary of run info (e.g. working dir, etc)
     @ In, inputs, list, list of inputs
     @ In, initDict, dict, dictionary with initialization options
    """
    BasePostProcessor.initialize(self, runInfo, inputs, initDict)
    self.__workingDir = runInfo['WorkingDir']
    for key in self.assemblerDict.keys():
      if 'Label' == key:
        indice = 0
        for _ in self.assemblerDict[key]:
          self.labelAlgorithms.append(self.assemblerDict[key][indice][3])
          indice += 1

  def _localReadMoreXML(self, xmlNode):
    """
      Method to read special input required for this post-processor
      @ In, xmlNode, Xml element node
      @ Out, None
    """
    for child in xmlNode:
      # FIXME is there anything that is a float that will raise an exception for int?
      if child.attrib:
        self.initializationOptionDict[child.tag] = {}
        self.initializationOptionDict[child.tag].update(child.attrib)
      else:
        try: self.initializationOptionDict[child.tag] = utils.intConversion(child.text)
        except ValueError:
          try: self.initializationOptionDict[child.tag] = float(child.text)
          except ValueError: self.initializationOptionDict[child.tag] = child.text
      if child.tag == 'KDD':
        if child.attrib:
          if 'lib' in child.attrib.keys():
            self.type = child.attrib.values()[0]
            self.initializationOptionDict[child.tag].pop('lib')
        for childChild in child:
          if childChild.attrib:
            self.initializationOptionDict[child.tag][childChild.tag] = {}
            self.initializationOptionDict[child.tag][childChild.tag].update(childChild.attrib)
          else:
            try: self.initializationOptionDict[child.tag][childChild.tag] = int(childChild.text)
            except ValueError:
              try: self.initializationOptionDict[child.tag][childChild.tag] = float(childChild.text)
              except ValueError: self.initializationOptionDict[child.tag][childChild.tag] = childChild.text

    if self.type: self.unSupervisedEngine = unSupervisedLearning.returnInstance(self.type, self, **self.initializationOptionDict['KDD'])
    else        : self.raiseAnError(IOError, 'No Data Mining Algorithm is supplied!')

  def collectOutput(self, finishedjob, output):
    """
      Function to place all of the computed data into the output object
      @ In, finishedJob, jobhandler object, A JobHandler object that is in charge of running this post-processor
      @ In, output, object, The object where we want to place our computed results
      @ Out, None
    """
    if finishedjob.returnEvaluation() == -1: self.raiseAnError(RuntimeError, 'No available Output to collect (Run probably is not finished yet)')
    self.raiseADebug(str(finishedjob.returnEvaluation()))
    dataMineDict = finishedjob.returnEvaluation()[1]
    for key in dataMineDict['output']:
      for param in output.getParaKeys('output'):
        if key == param: output.removeOutputValue(key)
      for value in dataMineDict['output'][key]: output.updateOutputValue(key, copy.copy(value))

  def run(self, InputIn):
    """
     This method executes the postprocessor action. In this case it loads the results to specified dataObject
     @ In , InputIn, dict, dictionary of data to process
     @ Out, outputdict, dict, dictionary containing the post-processed results
    """
    if len(self.dataObjects) is not 0:
      if type(self.dataObjects) == list: dataObject = self.dataObjects[-1]
      else                             : dataObject = self.dataObjects
    else: dataObject = None
    Input = self.inputToInternal(InputIn)

    outputDict = {}
    self.unSupervisedEngine.features = Input['Features']
    if not self.unSupervisedEngine.amITrained:  self.unSupervisedEngine.train(Input['Features'])

    self.unSupervisedEngine.confidence()
    outputDict['output'] = {}
    noClusters = 1
    if 'cluster' == self.unSupervisedEngine.SKLtype:
        if hasattr(self.unSupervisedEngine, 'labels_'):
          self.clusterLabels = self.unSupervisedEngine.labels_
        outputDict['output'][self.name+'Labels'] = self.clusterLabels;
        if hasattr(self.unSupervisedEngine, 'noClusters'): noClusters = self.unSupervisedEngine.noClusters
        if hasattr(self.unSupervisedEngine, 'clusterCentersIndices_'): noClusters = len(self.unSupervisedEngine.clusterCentersIndices_)
        for k in range(noClusters):
          if hasattr(self.unSupervisedEngine, 'clusterCenters_'): clusterCenter = self.unSupervisedEngine.clusterCenters_[k]
        if hasattr(self.unSupervisedEngine, 'inertia_') : inertia = self.unSupervisedEngine.inertia_
    if 'bicluster' == self.unSupervisedEngine.SKLtype:
        print ('Not yet implemented!...', self.unSupervisedEngine.SKLtype)
    if 'mixture' == self.unSupervisedEngine.SKLtype:
        if   hasattr(self.unSupervisedEngine, 'covars_'): mixtureCovars = self.unSupervisedEngine.covars_
        elif hasattr(self.unSupervisedEngine, 'precs_'): mixtureCovars = self.unSupervisedEngine.precs_
        mixtureValues = self.unSupervisedEngine.normValues
        mixtureMeans = self.unSupervisedEngine.means_
        mixtureLabels = self.unSupervisedEngine.evaluate(Input['Features'])
        outputDict['output'][self.name+'Labels'] = mixtureLabels
    if 'manifold' == self.unSupervisedEngine.SKLtype:
        manifoldValues = self.unSupervisedEngine.normValues
        if hasattr(self.unSupervisedEngine, 'embeddingVectors_'): embeddingVectors = self.unSupervisedEngine.embeddingVectors_
        if hasattr(self.unSupervisedEngine, 'reconstructionError_'): reconstructionError = self.unSupervisedEngine.reconstructionError_
        if   'transform'     in dir(self.unSupervisedEngine.Method): embeddingVectors = self.unSupervisedEngine.Method.transform(manifoldValues)
        elif 'fit_transform' in dir(self.unSupervisedEngine.Method): embeddingVectors = self.unSupervisedEngine.Method.fit_transform(manifoldValues)
        for i in range(len(embeddingVectors[0, :])):
          outputDict['output'][self.name+'EmbeddingVector' + str(i + 1)] =  embeddingVectors[:, i]
    if 'decomposition' == self.unSupervisedEngine.SKLtype:
        decompositionValues = self.unSupervisedEngine.normValues
        if hasattr(self.unSupervisedEngine, 'noComponents_'): noComponents = self.unSupervisedEngine.noComponents_
        if hasattr(self.unSupervisedEngine, 'components_'): components = self.unSupervisedEngine.components_
        if hasattr(self.unSupervisedEngine, 'explainedVarianceRatio_'): explainedVarianceRatio = self.unSupervisedEngine.explainedVarianceRatio_
        # SCORE method does not work for SciKit Learn 0.14
        # if hasattr(self.unSupervisedEngine.Method, 'score'): score = self.unSupervisedEngine.Method.score(decompositionValues)
        if   'transform'     in dir(self.unSupervisedEngine.Method): components = self.unSupervisedEngine.Method.transform(decompositionValues)
        elif 'fit_transform' in dir(self.unSupervisedEngine.Method): components = self.unSupervisedEngine.Method.fit_transform(decompositionValues)
        for i in range(noComponents):
          outputDict['output'][self.name+'PCAComponent' + str(i + 1)] =  components[:, i]
    return outputDict

"""
 Interface Dictionary (factory) (private)
"""
__base = 'PostProcessor'
__interFaceDict = {}
__interFaceDict['SafestPoint'              ] = SafestPoint
__interFaceDict['LimitSurfaceIntegral'     ] = LimitSurfaceIntegral
__interFaceDict['PrintCSV'                 ] = PrintCSV
__interFaceDict['BasicStatistics'          ] = BasicStatistics
__interFaceDict['InterfacedPostProcessor'  ] = InterfacedPostProcessor
__interFaceDict['LoadCsvIntoInternalObject'] = LoadCsvIntoInternalObject
__interFaceDict['LimitSurface'             ] = LimitSurface
__interFaceDict['ComparisonStatistics'     ] = ComparisonStatistics
__interFaceDict['External'                 ] = ExternalPostProcessor
__interFaceDict['TopologicalDecomposition' ] = TopologicalDecomposition
__interFaceDict['DataMining'               ] = DataMining
__knownTypes = __interFaceDict.keys()

def knownTypes():
  return __knownTypes

def returnInstance(Type, caller):
  """
    function used to generate a Filter class
    @ In, Type : Filter type
    @ Out,Instance of the Specialized Filter class
  """
  try: return __interFaceDict[Type](caller.messageHandler)
  except KeyError: caller.raiseAnError(NameError, 'not known ' + __base + ' type ' + Type)

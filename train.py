from typing import List
from state import checkIfGameIsWon, getAvailableMoves, makeMove, getStringRepresentation
from model import Net, loss, device, saveModel, loadLatetestModel
from mcts import MontecarloTreeSearch, Node, getAction
import numpy as np
import os
import torch
import copy 
from torch.optim import Adam, SGD
from copy import deepcopy as dc

# TODO: Load the last model
# TODO: During training the model should get different initial states
# TODO: Move to minibatch

def playGame (state: np.array, m1: Net, m2: Net) -> int:
    """ Returns 1 if m1 won the game, 0 if its a draw and -1 if m2 won """
    turn = 1
    
    while (checkIfGameIsWon(state) == -1):
        if ((turn % 2) == 0): 
            # M1 plays a move
            state = -makeMove(state, getAction(state.copy(), 25, m1)) # Now state is from the view of the other player
            
        else:
            # M2 plays a move
            state = -makeMove(state, getAction(state.copy(), 25, m2)) # Now state is from the view of the other player
            
        turn += 1
        # print(getStringRepresentation(state))
    
    # print(getStringRepresentation(state))
    # Check who won or drew the game.
    return checkIfGameIsWon(state) if (turn % 2 == 0) else -checkIfGameIsWon(state)

def evaluateModel (model: Net) -> int:
    """ Tests a model against the current best """
    score = 0
    best = loadLatetestModel()
    state = np.zeros((6, 7), dtype = "float32")
    # TODO: Go back to state.shape[1] instead of "1"
    for idx in range(1): # Test a position at each starting position
        s = -makeMove(state.copy(), idx)
        # print(getStringRepresentation(s))
        
        score += playGame(s.copy(), model, best)
        score -= playGame(s.copy(), best, model)
        
    return score   
    
def createTrainingDataset (model: Net, numberOfGames: int = 100, mctsSimulations: int = 25) -> List[List[np.array]]:
    """ Creates a training dataset for the model """
    dataset = []
    for _ in range(numberOfGames): # Create n games, to train the neural network upon
        dataset += executeEpisode(np.zeros((6, 7), dtype = "float32"), model, mctsSimulations)
    return dataset

def assignRewards (examples: List[List[np.array]], reward: float) -> List[List[np.array]]:
    """" Loop through the examples and assign them the reward """
    n = len(examples)
    for i in reversed(range(n)): # Loop through the examples backwards
        if (i % 2 != n % 2): # NOTE: The rewards are converted to match the output of the neural network
            examples[i][-1] = np.array([[-reward]], dtype = "float32") # This player lost the game
        else: 
            examples[i][-1] = np.array([[reward]], dtype = "float32") # This player won the game
    return examples

def addMirrorsToExamples (examples: List[List[np.array]]) -> List[List[np.array]]:
    """ Takes a list of examples and adds the mirror image of each state to the dataset """
    # 1. Create a list of mirrors
    mirrors = []
    for ex in examples:
        mirrors.append([np.flip(ex[0], 1), ex[1], ex[2]])
    
    # 2. Concatenate results    
    result = mirrors + examples
    np.random.shuffle(result) # Shuffle results for better learning
    return result
    
def executeEpisode (state: np.array, model: Net, mctsSimulations: int) -> List[List[np.array]]:
    """ Executes an episode and returns """ 
    examples = []
    while True:
        root = MontecarloTreeSearch(state.copy(), mctsSimulations, model)
        examples.append([state, root.probabilities * getAvailableMoves(state), None])
        action = root.selectAction(1) # NOTE: This should be increased during training 
        state = makeMove(state, action)
        
        reward = checkIfGameIsWon(state)
        if (reward != -1):
            # The game is ether won or drawn
            examples.append([state, np.zeros((1, 7), dtype = "float32"), None])
            return assignRewards(addMirrorsToExamples(examples), reward)
        else:
            # The game is not over yet
            state *= -1

def train (model: Net, previousIteration: int = 0, epochs: int = 4_000, iterations: int = 10, gamesPerIterations: int = 50, mctsSimulations: int = 25) -> Net:
    """ Trains a neural network to play connect 4, using the alpha zero algorithm """
    # Save the best model for evaluation of updated models
    improvement = False
    for iteration in range(iterations):
        if (iteration != 0 and improvement == False):
            # Load the latest model
            model = loadLatetestModel()
        # Create dataset
        print(f"\nAt iteration {iteration + 1} / {iterations}")
        dataset = createTrainingDataset(model, numberOfGames = gamesPerIterations, mctsSimulations = mctsSimulations)
        print(f" - Created a dataset of {len(dataset)} examples.")
        # Update model weights
        print(f" - Updating model weights.")
        model = updateWeights(model, epochs, dataset)
        
        # Pit the models against each other
        print(" - Evaluating model...")
        wins = evaluateModel(model)
        print(f"    * Model score: {wins}.")
        if (wins > 0): 
            saveModel(model, str(iteration + 1 + previousIteration) + ".pt")
            improvement = True
        else:
            improvement = False
    
    return loadLatetestModel()
        
def convertDatasetToNumpyArrays (dataset: List[List[np.array]]) -> (np.array):
    """ Converts the training dataset to 3d tensors for the model """
    arrays = []
    for idx in range(len(dataset[0])):
        arrays.append([item[idx] for item in dataset])

    arrays = [np.stack(array) for array in arrays]
    return arrays[0], arrays[1], arrays[2]    
    
def updateWeights (model: Net, epochs: int, dataset: List[List[np.array]]) -> Net:
    """ Creates a copy of the network, updates it's weights and returns """  
    # 1. Convert dataset
    s, p, r = convertDatasetToNumpyArrays(dataset)
    
    # 1.1 Move datasets to gpu
    states = torch.from_numpy(s.reshape(s.shape[0], 1, s.shape[1], s.shape[2])).float().to(model.device)
    probs = torch.from_numpy(p.reshape(p.shape[0], p.shape[2])).float().to(model.device) # TODO: Reshape these
    rewards = torch.from_numpy(r.reshape(r.shape[0], r.shape[2])).float().to(model.device) # TODO: Reshape these
    
    # 1.2 Move model to GPU
    model.cuda()

    # 2. Initialize optimizer
    optimizer = Adam(model.parameters(), lr = 0.001)  
    
    # 3. Run training loop 
    printTime = epochs // 5
    for e in range(epochs):
        optimizer.zero_grad()
        
        outputs = model(states)
        l = loss(outputs, (probs, rewards)) # TODO: I think that the current loss function is fucked.
        l.backward()
        optimizer.step()
        
        if ((e + 1) % printTime == 0):
            print(f"    * At epoch {(e + 1) / 1_000:.1f}k / {epochs // 1_000}k, with loss: {l.item():.3f}")
        elif (e == 0):
            print(f"    * At epoch 1 / {epochs // 1_000}k, with loss: {l.item():.3f}")
    
    # 4. Move model to cpu
    model.cpu()
    
    # Return model
    return model

if __name__ == "__main__":
    # TODO: Load the last best model
    if (len(os.listdir(os.path.join(os.getcwd(), "models"))) != 0):
        file = sorted(os.listdir(os.path.join(os.getcwd(), "models")))[-1]
        previousIteration = int(file.split(".")[0])
        model = loadLatetestModel()
    else:    
        model = Net()
        previousIteration = 0
        saveModel(model, "0.pt")
        
    print(f"Initializing training of the {model.numberOfTrainableParameters} learnable parameters")
    model = train(model, previousIteration = previousIteration, iterations = 100, epochs = 4_000, gamesPerIterations = 25)
    # print(executeEpisode(np.zeros((6, 7), dtype = "float32"), model, 25))